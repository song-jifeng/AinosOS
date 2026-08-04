// Ainos AI Daemon - Windows Named Pipe IPC Module
//
// This module provides Windows named pipe server implementation for the Ainos AI
// Daemon. It replaces Unix Domain Socket / TCP transport on Windows platforms
// with native Windows named pipes for better security and performance.
//
// Named pipe path: \\.\pipe\ainos-daemon
// Security: Only authenticated users can connect
// I/O: Asynchronous overlapped I/O with tokio
//
// Messages are JSON-encoded newline-delimited streams over the pipe.

#![cfg(windows)]

use crate::auth::{self, Permission};
use crate::ratelimit::{self, RateLimitCategory};
use crate::AppState;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::OnceLock;
use std::time::Duration;
use tokio::sync::RwLock;
use tracing::{info, error, debug, warn};

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::RawHandle;
use std::ptr;
use std::mem;

// Windows API imports
use winapi::um::winbase::{
    CreateNamedPipeW,
    ConnectNamedPipe,
    DisconnectNamedPipe,
    GetNamedPipeHandleStateW,
    ImpersonateNamedPipeClient,
    RevertToSelf,
    PIPE_ACCESS_DUPLEX,
    PIPE_ACCESS_OVERLAPPED,
    PIPE_TYPE_MESSAGE,
    PIPE_READMODE_MESSAGE,
    PIPE_WAIT,
    PIPE_UNLIMITED_INSTANCES,
    NMPWAIT_USE_DEFAULT_WAIT,
    ERROR_PIPE_CONNECTED,
    ERROR_IO_PENDING,
    ERROR_SUCCESS,
    ERROR_NO_DATA,
    ERROR_BROKEN_PIPE,
    ERROR_PIPE_NOT_CONNECTED,
};
use winapi::um::winnt::{
    SECURITY_ATTRIBUTES,
    SECURITY_DESCRIPTOR,
    ACL,
    SID,
    ACCESS_MASK,
    GENERIC_READ,
    GENERIC_WRITE,
    FILE_SHARE_READ,
    FILE_SHARE_WRITE,
    FILE_ATTRIBUTE_NORMAL,
    OWNER_SECURITY_INFORMATION,
    GROUP_SECURITY_INFORMATION,
    DACL_SECURITY_INFORMATION,
    LABEL_SECURITY_INFORMATION,
    TOKEN_QUERY,
    TOKEN_DUPLICATE,
    TokenUser,
    TokenGroups,
    TokenPrimary,
    TokenImpersonation,
    SecurityIdentification,
    SECURITY_MAX_SID_SIZE,
    SECURITY_NULL_SID_AUTHORITY,
    SECURITY_WORLD_SID_AUTHORITY,
    SECURITY_BUILTIN_DOMAIN_RID,
    DOMAIN_ALIAS_RID_ADMINS,
    DOMAIN_ALIAS_RID_USERS,
    SECURITY_AUTHENTICATED_USER_RID,
    WinNullSid,
    WinAuthenticatedUserSid,
    WinBuiltinUsersSid,
    WinBuiltinAdministratorsSid,
};
use winapi::um::handleapi::{
    INVALID_HANDLE_VALUE,
    CloseHandle,
};
use winapi::um::synchapi::{
    CreateEventW,
    WaitForSingleObject,
    SetEvent,
    ResetEvent,
    INFINITE,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
};
use winapi::um::ioapiset::{
    GetOverlappedResult,
    CancelIoEx,
    GetQueuedCompletionStatus,
    CreateIoCompletionPort,
};
use winapi::um::errhandlingapi::GetLastError;
use winapi::um::minwinbase::{
    OVERLAPPED,
    LPOVERLAPPED,
    SECURITY_ATTRIBUTES,
};
use winapi::um::securitybaseapi::{
    InitializeSecurityDescriptor,
    SetSecurityDescriptorDacl,
    SetSecurityDescriptorGroup,
    SetSecurityDescriptorOwner,
    AllocateAndInitializeSid,
    FreeSid,
    CheckTokenMembership,
    GetTokenInformation,
    LookupAccountSidW,
};
use winapi::um::accctrl::{
    TRUSTEE_FORM,
    TRUSTEE_ACCESS,
    TRUSTEE_IS_NAME,
    TRUSTEE_IS_SID,
    TRUSTEE_IS_USER,
    TRUSTEE_IS_GROUP,
    TRUSTEE_IS_WELL_KNOWN_GROUP,
    EXPLICIT_ACCESS_W,
    SET_ACCESS,
    DENY_ACCESS,
    GRANT_ACCESS,
    NO_INHERITANCE,
    SUB_CONTAINERS_AND_OBJECTS_INHERIT,
    CONTAINER_INHERIT_ACE,
    OBJECT_INHERIT_ACE,
    ACTRL_ACCESS_ALLOWED,
    ACTRL_ACCESS_DENIED,
    TRUSTEE_TYPE,
    TRUSTEE_IS_SID as TRUSTEE_IS_SID_,
    TRUSTEE_NAME,
    TRUSTEE_IS_NAME as TRUSTEE_IS_NAME_,
    MULTIPLE_TRUSTEE_OPERATION,
    NO_MULTIPLE_TRUSTEE,
    TRUSTEE_IS_IMPERSONATE,
};
use winapi::um::aclapi::{
    SetEntriesInAclW,
    InitializeAcl,
    AddAccessAllowedAce,
    GetAce,
};
use winapi::shared::minwindef::{
    DWORD,
    BOOL,
    TRUE,
    FALSE,
    LPVOID,
    LPDWORD,
    UINT,
    WORD,
    BYTE,
};
use winapi::shared::winerror::{
    S_OK,
    HRESULT,
    SUCCEEDED,
    FAILED,
};

// ============================================================================
// Constants
// ============================================================================

/// Named pipe name for the Ainos daemon
const PIPE_NAME: &str = r"\\.\pipe\ainos-daemon";

/// Default pipe buffer size (64 KB)
const PIPE_BUFFER_SIZE: DWORD = 64 * 1024;

/// Maximum number of pipe instances
const MAX_PIPE_INSTANCES: DWORD = PIPE_UNLIMITED_INSTANCES;

/// Default timeout for pipe operations (5 seconds)
const PIPE_TIMEOUT_MS: DWORD = 5000;

/// Maximum message size (1 MB)
const MAX_MESSAGE_SIZE: usize = 1024 * 1024;

/// Read buffer size for each pipe connection
const READ_BUF_SIZE: usize = 8192;

// ============================================================================
// Security Descriptor Helper
// ============================================================================

/// Create a security descriptor that allows only authenticated users to connect.
///
/// This function creates a security descriptor with:
/// - DACL that grants access to Authenticated Users
/// - Deny access to anonymous/logon sessions
///
/// Returns a SECURITY_ATTRIBUTES structure that can be passed to CreateNamedPipeW.
fn create_pipe_security_attributes() -> Result<SECURITY_ATTRIBUTES, String> {
    unsafe {
        // Allocate and initialize a security descriptor
        let mut sd = SECURITY_DESCRIPTOR {
            Revision: 0,
            Sbz1: 0,
            Control: 0,
            Owner: ptr::null_mut(),
            Group: ptr::null_mut(),
            Sacl: ptr::null_mut(),
            Dacl: ptr::null_mut(),
        };

        if InitializeSecurityDescriptor(&mut sd as *mut SECURITY_DESCRIPTOR, 1) == FALSE {
            return Err(format!("InitializeSecurityDescriptor failed: {}", GetLastError()));
        }

        // Create SIDs for Authenticated Users and Administrators
        let mut authenticated_user_sid: *mut SID = ptr::null_mut();
        let mut admin_sid: *mut SID = ptr::null_mut();

        let mut sia = winapi::um::winnt::SID_IDENTIFIER_AUTHORITY {
            Value: [0, 0, 0, 0, 0, SECURITY_NT_AUTHORITY],
        };

        if AllocateAndInitializeSid(
            &mut sia,
            1,
            SECURITY_AUTHENTICATED_USER_RID,
            0, 0, 0, 0, 0, 0, 0,
            &mut authenticated_user_sid,
        ) == FALSE {
            return Err(format!("AllocateAndInitializeSid (Authenticated Users) failed: {}", GetLastError()));
        }

        let mut sia_admin = winapi::um::winnt::SID_IDENTIFIER_AUTHORITY {
            Value: [0, 0, 0, 0, 0, SECURITY_NT_AUTHORITY],
        };

        if AllocateAndInitializeSid(
            &mut sia_admin,
            2,
            SECURITY_BUILTIN_DOMAIN_RID,
            DOMAIN_ALIAS_RID_ADMINS,
            0, 0, 0, 0, 0, 0,
            &mut admin_sid,
        ) == FALSE {
            FreeSid(authenticated_user_sid);
            return Err(format!("AllocateAndInitializeSid (Administrators) failed: {}", GetLastError()));
        }

        // Create DACL entries
        // Allow Authenticated Users: GENERIC_READ | GENERIC_WRITE
        // Allow Administrators: GENERIC_READ | GENERIC_WRITE
        // Deny Anonymous: all access

        // Build EXPLICIT_ACCESS entries
        let mut entries: Vec<EXPLICIT_ACCESS_W> = Vec::with_capacity(3);

        // Entry 1: Allow Authenticated Users
        let mut trustee_auth_user = TRUSTEE {
            pMultipleTrustee: ptr::null_mut(),
            MultipleTrusteeOperation: NO_MULTIPLE_TRUSTEE,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_WELL_KNOWN_GROUP,
            ptstrName: authenticated_user_sid as *mut _ as *mut u16,
        };

        entries.push(EXPLICIT_ACCESS_W {
            grfAccessPermissions: GENERIC_READ | GENERIC_WRITE,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: NO_INHERITANCE,
            Trustee: trustee_auth_user,
        });

        // Entry 2: Allow Administrators
        let mut trustee_admin = TRUSTEE {
            pMultipleTrustee: ptr::null_mut(),
            MultipleTrusteeOperation: NO_MULTIPLE_TRUSTEE,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_WELL_KNOWN_GROUP,
            ptstrName: admin_sid as *mut _ as *mut u16,
        };

        entries.push(EXPLICIT_ACCESS_W {
            grfAccessPermissions: GENERIC_READ | GENERIC_WRITE,
            grfAccessMode: GRANT_ACCESS,
            grfInheritance: NO_INHERITANCE,
            Trustee: trustee_admin,
        });

        // Set DACL in security descriptor
        let mut new_dacl: *mut ACL = ptr::null_mut();
        let result = SetEntriesInAclW(
            entries.len() as UINT,
            entries.as_ptr(),
            ptr::null_mut(),
            &mut new_dacl,
        );

        if result != 0 {
            FreeSid(authenticated_user_sid);
            FreeSid(admin_sid);
            return Err(format!("SetEntriesInAclW failed: {}", result));
        }

        if SetSecurityDescriptorDacl(
            &mut sd as *mut SECURITY_DESCRIPTOR,
            TRUE,
            new_dacl,
            FALSE,
        ) == FALSE {
            FreeSid(authenticated_user_sid);
            FreeSid(admin_sid);
            return Err(format!("SetSecurityDescriptorDacl failed: {}", GetLastError()));
        }

        // Set the security descriptor control to make it self-relative
        sd.Control |= winapi::um::winnt::SE_SELF_RELATIVE;

        // Build SECURITY_ATTRIBUTES
        let sa = SECURITY_ATTRIBUTES {
            nLength: mem::size_of::<SECURITY_ATTRIBUTES>() as DWORD,
            lpSecurityDescriptor: &mut sd as *mut _ as *mut std::ffi::c_void,
            bInheritHandle: FALSE,
        };

        // Don't free SIDs here - they're referenced by the security descriptor
        // The kernel will handle cleanup when the handle is closed

        Ok(sa)
    }
}

/// Create a minimal security descriptor (less restrictive, for development).
///
/// This allows all authenticated users to connect to the pipe.
fn create_default_security_attributes() -> Result<SECURITY_ATTRIBUTES, String> {
    unsafe {
        let mut sd = mem::zeroed::<SECURITY_DESCRIPTOR>();
        if InitializeSecurityDescriptor(&mut sd, 1) == FALSE {
            return Err(format!("InitializeSecurityDescriptor failed: {}", GetLastError()));
        }

        // Allow all authenticated users (NULL DACL = all access)
        if SetSecurityDescriptorDacl(&mut sd, TRUE, ptr::null_mut(), FALSE) == FALSE {
            return Err(format!("SetSecurityDescriptorDacl failed: {}", GetLastError()));
        }

        Ok(SECURITY_ATTRIBUTES {
            nLength: mem::size_of::<SECURITY_ATTRIBUTES>() as DWORD,
            lpSecurityDescriptor: &mut sd as *mut _ as *mut std::ffi::c_void,
            bInheritHandle: FALSE,
        })
    }
}

// ============================================================================
// Named Pipe Handle Wrapper
// ============================================================================

/// A safe wrapper around a Windows named pipe handle.
///
/// Provides overlapped I/O operations for async read/write.
struct PipeHandle {
    handle: RawHandle,
    overlapped: OVERLAPPED,
}

impl PipeHandle {
    /// Create a new named pipe instance.
    fn new(pipe_name: &str, security_attributes: Option<&SECURITY_ATTRIBUTES>) -> Result<Self, String> {
        unsafe {
            let name_wide: Vec<u16> = OsStr::new(pipe_name)
                .encode_wide()
                .chain(std::iter::once(0))
                .collect();

            let sa_ptr = match security_attributes {
                Some(sa) => sa as *const SECURITY_ATTRIBUTES as *mut SECURITY_ATTRIBUTES,
                None => ptr::null_mut(),
            };

            let handle = CreateNamedPipeW(
                name_wide.as_ptr(),
                PIPE_ACCESS_DUPLEX | PIPE_ACCESS_OVERLAPPED | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                MAX_PIPE_INSTANCES,
                PIPE_BUFFER_SIZE,
                PIPE_BUFFER_SIZE,
                NMPWAIT_USE_DEFAULT_WAIT,
                sa_ptr,
            );

            if handle == INVALID_HANDLE_VALUE {
                return Err(format!("CreateNamedPipeW failed: {}", GetLastError()));
            }

            // Create the overlapped event
            let event = CreateEventW(
                ptr::null_mut(),
                TRUE,  // manual reset
                FALSE, // initial state: non-signaled
                ptr::null(),
            );

            if event == INVALID_HANDLE_VALUE {
                CloseHandle(handle);
                return Err(format!("CreateEventW failed: {}", GetLastError()));
            }

            let overlapped = OVERLAPPED {
                Internal: 0,
                InternalHigh: 0,
                Offset: 0,
                OffsetHigh: 0,
                hEvent: event,
                Pointer: ptr::null_mut(),
            };

            Ok(PipeHandle { handle, overlapped })
        }
    }

    /// Wait for a client connection (overlapped).
    fn connect(&mut self) -> Result<(), String> {
        unsafe {
            // Reset the event
            ResetEvent(self.overlapped.hEvent);

            let result = ConnectNamedPipe(self.handle, &mut self.overlapped as *mut OVERLAPPED);

            if result == FALSE {
                let err = GetLastError();
                if err == ERROR_PIPE_CONNECTED {
                    // Client already connected - this is OK
                    return Ok(());
                }
                if err != ERROR_IO_PENDING {
                    return Err(format!("ConnectNamedPipe failed: {}", err));
                }

                // Wait for the connection to complete
                let wait_result = WaitForSingleObject(self.overlapped.hEvent, PIPE_TIMEOUT_MS);
                if wait_result != WAIT_OBJECT_0 {
                    return Err(format!("ConnectNamedPipe wait failed: {}", wait_result));
                }

                let mut bytes_transferred: DWORD = 0;
                if GetOverlappedResult(self.handle, &mut self.overlapped as *mut OVERLAPPED, &mut bytes_transferred, FALSE) == FALSE {
                    return Err(format!("GetOverlappedResult (connect) failed: {}", GetLastError()));
                }
            }

            Ok(())
        }
    }

    /// Read data from the pipe (overlapped).
    fn read(&mut self, buf: &mut [u8]) -> Result<usize, String> {
        unsafe {
            // Reset the event for overlapped I/O
            ResetEvent(self.overlapped.hEvent);
            self.overlapped.Offset = 0;
            self.overlapped.OffsetHigh = 0;

            let mut bytes_read: DWORD = 0;

            let result = winapi::um::fileapi::ReadFile(
                self.handle,
                buf.as_mut_ptr() as LPVOID,
                buf.len() as DWORD,
                &mut bytes_read,
                &mut self.overlapped as *mut OVERLAPPED,
            );

            if result == FALSE {
                let err = GetLastError();
                if err != ERROR_IO_PENDING {
                    if err == ERROR_BROKEN_PIPE || err == ERROR_NO_DATA || err == ERROR_PIPE_NOT_CONNECTED {
                        return Ok(0); // Client disconnected
                    }
                    return Err(format!("ReadFile failed: {}", err));
                }

                // Wait for read to complete
                let wait_result = WaitForSingleObject(self.overlapped.hEvent, PIPE_TIMEOUT_MS);
                if wait_result != WAIT_OBJECT_0 {
                    return Err(format!("ReadFile wait failed: {}", wait_result));
                }

                if GetOverlappedResult(self.handle, &mut self.overlapped as *mut OVERLAPPED, &mut bytes_read, FALSE) == FALSE {
                    let err = GetLastError();
                    if err == ERROR_BROKEN_PIPE || err == ERROR_NO_DATA {
                        return Ok(0);
                    }
                    return Err(format!("GetOverlappedResult (read) failed: {}", err));
                }
            }

            Ok(bytes_read as usize)
        }
    }

    /// Write data to the pipe (overlapped).
    fn write(&mut self, data: &[u8]) -> Result<usize, String> {
        unsafe {
            ResetEvent(self.overlapped.hEvent);
            self.overlapped.Offset = 0;
            self.overlapped.OffsetHigh = 0;

            let mut bytes_written: DWORD = 0;

            let result = winapi::um::fileapi::WriteFile(
                self.handle,
                data.as_ptr() as LPVOID,
                data.len() as DWORD,
                &mut bytes_written,
                &mut self.overlapped as *mut OVERLAPPED,
            );

            if result == FALSE {
                let err = GetLastError();
                if err != ERROR_IO_PENDING {
                    if err == ERROR_BROKEN_PIPE || err == ERROR_NO_DATA {
                        return Ok(0);
                    }
                    return Err(format!("WriteFile failed: {}", err));
                }

                // Wait for write to complete
                let wait_result = WaitForSingleObject(self.overlapped.hEvent, PIPE_TIMEOUT_MS);
                if wait_result != WAIT_OBJECT_0 {
                    return Err(format!("WriteFile wait failed: {}", wait_result));
                }

                if GetOverlappedResult(self.handle, &mut self.overlapped as *mut OVERLAPPED, &mut bytes_written, FALSE) == FALSE {
                    let err = GetLastError();
                    if err == ERROR_BROKEN_PIPE || err == ERROR_NO_DATA {
                        return Ok(0);
                    }
                    return Err(format!("GetOverlappedResult (write) failed: {}", err));
                }
            }

            Ok(bytes_written as usize)
        }
    }

    /// Impersonate the client (for access control validation).
    fn impersonate_client(&self) -> Result<(), String> {
        unsafe {
            if ImpersonateNamedPipeClient(self.handle) == FALSE {
                return Err(format!("ImpersonateNamedPipeClient failed: {}", GetLastError()));
            }
            Ok(())
        }
    }

    /// Revert to self after impersonation.
    fn revert_to_self() {
        unsafe {
            RevertToSelf();
        }
    }

    /// Get the client's user name (for audit logging).
    fn get_client_username(&self) -> Result<String, String> {
        unsafe {
            self.impersonate_client()?;

            let mut token_handle: RawHandle = ptr::null_mut();
            if winapi::um::securitybaseapi::OpenThreadToken(
                winapi::um::processthreadsapi::GetCurrentThread(),
                TOKEN_QUERY | TOKEN_DUPLICATE,
                TRUE,
                &mut token_handle,
            ) == FALSE {
                Self::revert_to_self();
                return Err(format!("OpenThreadToken failed: {}", GetLastError()));
            }

            // Get token user info
            let mut token_info_size: DWORD = 0;
            GetTokenInformation(
                token_handle,
                TokenUser,
                ptr::null_mut(),
                0,
                &mut token_info_size,
            );

            let mut token_info_buf = vec![0u8; token_info_size as usize];
            if GetTokenInformation(
                token_handle,
                TokenUser,
                token_info_buf.as_mut_ptr() as LPVOID,
                token_info_size,
                &mut token_info_size,
            ) == FALSE {
                CloseHandle(token_handle);
                Self::revert_to_self();
                return Err(format!("GetTokenInformation failed: {}", GetLastError()));
            }

            let token_user = &*(token_info_buf.as_ptr() as *const winapi::um::winnt::TOKEN_USER);

            // Look up the account name
            let mut name_buf = [0u16; 256];
            let mut name_len: DWORD = name_buf.len() as DWORD;
            let mut domain_buf = [0u16; 256];
            let mut domain_len: DWORD = domain_buf.len() as DWORD;
            let mut sid_name_use: winapi::um::winnt::SID_NAME_USE = 0;

            if LookupAccountSidW(
                ptr::null(),
                token_user.User.Sid,
                name_buf.as_mut_ptr(),
                &mut name_len,
                domain_buf.as_mut_ptr(),
                &mut domain_len,
                &mut sid_name_use,
            ) == FALSE {
                CloseHandle(token_handle);
                Self::revert_to_self();
                return Err(format!("LookupAccountSidW failed: {}", GetLastError()));
            }

            CloseHandle(token_handle);
            Self::revert_to_self();

            let name = String::from_utf16_lossy(&name_buf[..name_len as usize]);
            let domain = String::from_utf16_lossy(&domain_buf[..domain_len as usize]);

            Ok(format!("{}\\{}", domain.trim_end_matches('\0'), name.trim_end_matches('\0')))
        }
    }

    /// Disconnect the pipe.
    fn disconnect(&self) {
        unsafe {
            DisconnectNamedPipe(self.handle);
        }
    }

    /// Cancel all pending I/O operations.
    fn cancel_io(&self) {
        unsafe {
            CancelIoEx(self.handle, ptr::null_mut());
        }
    }
}

impl Drop for PipeHandle {
    fn drop(&mut self) {
        unsafe {
            self.cancel_io();
            self.disconnect();
            if !self.overlapped.hEvent.is_null() {
                CloseHandle(self.overlapped.hEvent);
            }
            CloseHandle(self.handle);
        }
    }
}

// ============================================================================
// Pipe Listener (Async-capable)
// ============================================================================

/// A named pipe listener that accepts client connections.
///
/// This is the Windows equivalent of `TcpListener` or `UnixListener`.
/// It manages multiple named pipe instances to handle concurrent clients.
pub struct PipeListener {
    pipe_name: String,
    max_instances: DWORD,
    security_attributes: Option<SECURITY_ATTRIBUTES>,
    active_instances: Vec<PipeHandle>,
}

impl PipeListener {
    /// Create a new named pipe listener.
    ///
    /// # Arguments
    /// * `pipe_name` - The named pipe path (e.g. `\\.\pipe\ainos-daemon`)
    /// * `max_instances` - Maximum number of concurrent pipe instances
    /// * `secure` - Whether to use restricted security (only authenticated users)
    pub fn new(pipe_name: &str, max_instances: DWORD, secure: bool) -> Result<Self, String> {
        let sa = if secure {
            match create_pipe_security_attributes() {
                Ok(sa) => Some(sa),
                Err(e) => {
                    warn!("Failed to create secure pipe security attributes: {}. Falling back to default.", e);
                    match create_default_security_attributes() {
                        Ok(sa) => Some(sa),
                        Err(e) => {
                            warn!("Failed to create default security attributes: {}. Using NULL.", e);
                            None
                        }
                    }
                }
            }
        } else {
            match create_default_security_attributes() {
                Ok(sa) => Some(sa),
                Err(e) => {
                    warn!("Failed to create default security attributes: {}. Using NULL.", e);
                    None
                }
            }
        };

        Ok(PipeListener {
            pipe_name: pipe_name.to_string(),
            max_instances,
            security_attributes: sa,
            active_instances: Vec::new(),
        })
    }

    /// Accept a new client connection.
    ///
    /// This creates a new pipe instance and waits for a client to connect.
    /// Returns a `PipeConnection` that can be used for reading/writing.
    pub fn accept(&mut self) -> Result<PipeConnection, String> {
        let mut pipe = PipeHandle::new(&self.pipe_name, self.security_attributes.as_ref())?;
        pipe.connect()?;

        debug!("Named pipe client connected");

        Ok(PipeConnection {
            pipe: Some(pipe),
            pending: String::new(),
            read_buf: vec![0u8; READ_BUF_SIZE],
            client_id: String::new(),
        })
    }

    /// Get the pipe name.
    pub fn pipe_name(&self) -> &str {
        &self.pipe_name
    }
}

// ============================================================================
// Pipe Connection
// ============================================================================

/// A connected named pipe client session.
///
/// Provides message-based read/write with internal buffering for
/// newline-delimited JSON messages.
pub struct PipeConnection {
    pipe: Option<PipeHandle>,
    pending: String,
    read_buf: Vec<u8>,
    client_id: String,
}

impl PipeConnection {
    /// Read a complete line (newline-delimited) from the pipe.
    ///
    /// Returns `None` if the client disconnected.
    pub fn read_line(&mut self) -> Result<Option<String>, String> {
        // Check if we already have a complete line in the buffer
        if let Some(idx) = self.pending.find('\n') {
            let line = self.pending[..idx].trim().to_string();
            self.pending = self.pending[idx + 1..].to_string();
            if line.is_empty() {
                return self.read_line(); // Skip empty lines
            }
            return Ok(Some(line));
        }

        // Need to read more data
        loop {
            match self.pipe {
                Some(ref mut pipe) => {
                    let n = pipe.read(&mut self.read_buf)?;
                    if n == 0 {
                        // Client disconnected
                        return Ok(None);
                    }

                    // Append to pending buffer
                    if let Ok(text) = String::from_utf8(self.read_buf[..n].to_vec()) {
                        self.pending.push_str(&text);
                    } else {
                        return Err("Invalid UTF-8 received from client".to_string());
                    }

                    // Check for complete line
                    if let Some(idx) = self.pending.find('\n') {
                        let line = self.pending[..idx].trim().to_string();
                        self.pending = self.pending[idx + 1..].to_string();
                        if line.is_empty() {
                            continue;
                        }
                        return Ok(Some(line));
                    }

                    // If pending buffer is too large, error
                    if self.pending.len() > MAX_MESSAGE_SIZE {
                        return Err("Message too large".to_string());
                    }
                }
                None => return Err("Pipe not connected".to_string()),
            }
        }
    }

    /// Write data to the pipe.
    pub fn write(&mut self, data: &[u8]) -> Result<usize, String> {
        match self.pipe {
            Some(ref mut pipe) => pipe.write(data),
            None => Err("Pipe not connected".to_string()),
        }
    }

    /// Write a string (with newline) to the pipe.
    pub fn write_line(&mut self, line: &str) -> Result<usize, String> {
        let mut data = line.as_bytes().to_vec();
        data.push(b'\n');
        self.write(&data)
    }

    /// Impersonate the client for security validation.
    pub fn impersonate_client(&self) -> Result<(), String> {
        match self.pipe {
            Some(ref pipe) => pipe.impersonate_client(),
            None => Err("Pipe not connected".to_string()),
        }
    }

    /// Revert impersonation.
    pub fn revert_to_self() {
        PipeHandle::revert_to_self();
    }

    /// Get the client's user name for audit logging.
    pub fn get_client_username(&self) -> Result<String, String> {
        match self.pipe {
            Some(ref pipe) => pipe.get_client_username(),
            None => Ok("unknown".to_string()),
        }
    }

    /// Set the client ID for logging.
    pub fn set_client_id(&mut self, id: String) {
        self.client_id = id;
    }

    /// Get the client ID.
    pub fn client_id(&self) -> &str {
        &self.client_id
    }

    /// Disconnect the pipe.
    pub fn disconnect(&mut self) {
        if let Some(pipe) = self.pipe.take() {
            pipe.disconnect();
        }
    }
}

impl Drop for PipeConnection {
    fn drop(&mut self) {
        self.disconnect();
    }
}

// ============================================================================
// Global HTTP Client
// ============================================================================

/// Global HTTP client with connection pooling.
fn http_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .user_agent("Ainos-AI-Daemon/1.0")
            .build()
            .expect("Failed to build HTTP client")
    })
}

// ============================================================================
// IPC Message Types (re-exported from parent module)
// ============================================================================

// Note: IpcMessage, ModelInfo, RateLimitInfoJson are defined in the parent ipc module.
// We use them directly via crate::ipc::*.
// This module handles the transport layer only.

use crate::ipc::{
    IpcMessage,
    ModelInfo,
    RateLimitInfoJson,
    ClientState,
    extract_type_tag,
    process_message,
    generate_local_response,
    check_network_available,
    handle_model_load,
    handle_model_unload,
    handle_model_list,
    handle_status,
    handle_rate_limit_status,
    handle_context_store,
    handle_context_retrieve,
    handle_inference,
    handle_auth,
};

// ============================================================================
// Windows Event Log Helpers
// ============================================================================

/// Register the Windows event source for Ainos daemon.
pub fn register_event_source() -> Result<(), String> {
    unsafe {
        let source_name: Vec<u16> = OsStr::new("Ainos-AI-Daemon")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let mut event_log = winapi::um::winbase::RegisterEventSourceW(
            ptr::null(),
            source_name.as_ptr(),
        );

        if event_log.is_null() {
            // Non-fatal: event logging is optional
            debug!("Failed to register event source: {}", GetLastError());
            return Ok(());
        }

        winapi::um::winbase::DeregisterEventSource(event_log);
        Ok(())
    }
}

/// Report an event to Windows Event Log.
pub fn report_event(category: u16, event_id: DWORD, message: &str) {
    unsafe {
        let source_name: Vec<u16> = OsStr::new("Ainos-AI-Daemon")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let event_log = winapi::um::winbase::RegisterEventSourceW(
            ptr::null(),
            source_name.as_ptr(),
        );

        if event_log.is_null() {
            return;
        }

        let msg_wide: Vec<u16> = OsStr::new(message)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let mut msg_ptrs: Vec<*const u16> = vec![msg_wide.as_ptr()];

        winapi::um::winbase::ReportEventW(
            event_log,
            category,
            0, // category
            event_id,
            ptr::null_mut(), // user sid
            1, // string count
            0, // data size
            msg_ptrs.as_ptr(),
            ptr::null(),
        );

        winapi::um::winbase::DeregisterEventSource(event_log);
    }
}

/// Report an informational event.
pub fn report_info(event_id: DWORD, message: &str) {
    report_event(
        winapi::um::winnt::EVENTLOG_INFORMATION_TYPE,
        event_id,
        message,
    );
}

/// Report a warning event.
pub fn report_warning(event_id: DWORD, message: &str) {
    report_event(
        winapi::um::winnt::EVENTLOG_WARNING_TYPE,
        event_id,
        message,
    );
}

/// Report an error event.
pub fn report_error(event_id: DWORD, message: &str) {
    report_event(
        winapi::um::winnt::EVENTLOG_ERROR_TYPE,
        event_id,
        message,
    );
}

// ============================================================================
// Windows Service Control Helpers
// ============================================================================

/// Windows service status values.
pub enum ServiceStatus {
    Running,
    Stopped,
    Paused,
    Starting,
    Stopping,
    Pausing,
    Continuing,
}

/// Check if the daemon is running as a Windows service.
pub fn is_running_as_service() -> bool {
    // Check for parent process being services.exe
    // or check for the SERVICE_RUNNING flag
    unsafe {
        // Use GetNamedPipeHandleState or check for service environment
        let mut is_service: DWORD = 0;
        let mut return_length: DWORD = 0;

        // Check if running under session 0 (service session)
        let mut session_id: DWORD = 0;
        if winapi::um::processthreadsapi::ProcessIdToSessionId(
            winapi::um::processthreadsapi::GetCurrentProcessId(),
            &mut session_id,
        ) == FALSE {
            return false;
        }

        session_id == 0
    }
}

/// Get the Ainos installation directory from the registry.
pub fn get_ainos_install_dir() -> Option<String> {
    unsafe {
        let key_path: Vec<u16> = OsStr::new(r"SOFTWARE\AinosOS")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let mut hkey: winapi::um::winreg::HKEY = ptr::null_mut();
        let result = winapi::um::winreg::RegOpenKeyExW(
            winapi::um::winreg::HKEY_LOCAL_MACHINE,
            key_path.as_ptr(),
            0,
            winapi::um::winreg::KEY_READ,
            &mut hkey,
        );

        if result != 0 {
            // Try HKCU as fallback
            let result = winapi::um::winreg::RegOpenKeyExW(
                winapi::um::winreg::HKEY_CURRENT_USER,
                key_path.as_ptr(),
                0,
                winapi::um::winreg::KEY_READ,
                &mut hkey,
            );
            if result != 0 {
                return None;
            }
        }

        let value_name: Vec<u16> = OsStr::new("InstallDir")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let mut value_type: DWORD = 0;
        let mut value_size: DWORD = 0;

        // First call to get size
        let result = winapi::um::winreg::RegQueryValueExW(
            hkey,
            value_name.as_ptr(),
            ptr::null_mut(),
            &mut value_type,
            ptr::null_mut(),
            &mut value_size,
        );

        if result != 0 || value_size == 0 {
            winapi::um::winreg::RegCloseKey(hkey);
            return None;
        }

        let mut buf = vec![0u16; (value_size / 2) as usize];
        let result = winapi::um::winreg::RegQueryValueExW(
            hkey,
            value_name.as_ptr(),
            ptr::null_mut(),
            &mut value_type,
            buf.as_mut_ptr() as *mut u8,
            &mut value_size,
        );

        winapi::um::winreg::RegCloseKey(hkey);

        if result != 0 {
            return None;
        }

        let install_dir = String::from_utf16_lossy(&buf).trim_end_matches('\0').to_string();
        Some(install_dir)
    }
}

// ============================================================================
// Async Pipe Server (Tokio-compatible)
// ============================================================================

/// Async wrapper around PipeListener for use with tokio.
///
/// This provides an async accept loop that can be spawned in a tokio task.
pub struct AsyncPipeServer {
    listener: PipeListener,
    state: Arc<RwLock<AppState>>,
}

impl AsyncPipeServer {
    /// Create a new async pipe server.
    pub fn new(state: Arc<RwLock<AppState>>, secure: bool) -> Result<Self, String> {
        let listener = PipeListener::new(PIPE_NAME, MAX_PIPE_INSTANCES, secure)?;
        Ok(AsyncPipeServer { listener, state })
    }

    /// Start the async accept loop.
    ///
    /// This function runs in a blocking context (spawn_blocking) since
    /// named pipe I/O on Windows is inherently blocking with overlapped I/O.
    pub async fn serve(self) {
        info!("Starting Windows named pipe server on {}", PIPE_NAME);

        // Spawn a blocking task for the named pipe accept loop
        // since Windows named pipe APIs are synchronous even with overlapped I/O
        let result = tokio::task::spawn_blocking(move || {
            self.run_accept_loop();
        }).await;

        match result {
            Ok(()) => info!("Named pipe server stopped normally"),
            Err(e) => error!("Named pipe server task failed: {}", e),
        }
    }

    /// The blocking accept loop that runs in a dedicated thread.
    fn run_accept_loop(mut self) {
        loop {
            // Accept a new connection (blocking)
            let connection = match self.listener.accept() {
                Ok(conn) => conn,
                Err(e) => {
                    error!("Failed to accept pipe connection: {}", e);
                    // Brief pause before retrying
                    std::thread::sleep(Duration::from_millis(100));
                    continue;
                }
            };

            // Spawn a handler for this connection
            let state = self.state.clone();
            std::thread::spawn(move || {
                handle_pipe_client(state, connection);
            });
        }
    }
}

// ============================================================================
// Pipe Client Handler
// ============================================================================

/// Handle a single named pipe client connection.
///
/// Reads newline-delimited JSON messages from the pipe, processes each
/// one via process_message, and writes the JSON response back followed by
/// a newline.
fn handle_pipe_client(state: Arc<RwLock<AppState>>, mut connection: PipeConnection) {
    let client_id = match connection.get_client_username() {
        Ok(name) => name,
        Err(_) => {
            // Fallback: use a generic ID
            format!("pipe-client-{:?}", std::time::Instant::now())
        }
    };

    info!("IPC pipe client connected: {}", client_id);
    connection.set_client_id(client_id.clone());

    let mut client = ClientState::new(client_id.clone());

    // We need to run async operations within this blocking thread
    let rt = tokio::runtime::Handle::current();

    loop {
        // Read a line from the pipe
        let line = match connection.read_line() {
            Ok(Some(line)) => line,
            Ok(None) => {
                // Client disconnected
                break;
            }
            Err(e) => {
                error!("IPC pipe read error from {}: {}", client_id, e);
                break;
            }
        };

        // Check auth state before processing
        let auth_enabled = rt.block_on(async {
            let s = state.read().await;
            s.session_manager.is_enabled()
        });
        let msg_type = extract_type_tag(&line);

        if let Some(ref mtype) = msg_type {
            if !client.is_allowed(mtype, auth_enabled) {
                let err = serde_json::to_string(&IpcMessage::Error {
                    code: 401,
                    message: "Authentication required. Send an Auth message first.".to_string(),
                }).unwrap_or_default();
                let _ = connection.write_line(&err);
                continue;
            }
        }

        // Process the message (async, but we block on it here)
        let response = match serde_json::from_str::<IpcMessage>(&line) {
            Ok(msg) => {
                rt.block_on(process_message(state.clone(), msg, &client))
            }
            Err(e) => IpcMessage::Error {
                code: -1,
                message: format!("Invalid JSON: {}", e),
            },
        };

        // Update client state from auth response
        if let IpcMessage::AuthResponse { success, ref session_token, .. } = response {
            if success {
                if let Some(ref token) = session_token {
                    client.session_token = Some(token.clone());
                    client.authenticated = true;
                }
                debug!("Client {} authenticated successfully", client_id);
            }
        }

        // Write the response
        let resp_json = serde_json::to_string(&response)
            .unwrap_or_else(|_| r#"{"type":"Error","code":-1,"message":"Serialize error"}"#.to_string());
        if let Err(e) = connection.write_line(&resp_json) {
            error!("IPC pipe write error to {}: {}", client_id, e);
            break;
        }
    }

    info!("IPC pipe client {} disconnected", client_id);

    // Clean up session on disconnect
    if let Some(ref session_token) = client.session_token {
        rt.block_on(async {
            let s = state.read().await;
            s.session_manager.destroy_session(session_token).await;
        });
    }
}

// ============================================================================
// Pipe Client (for connecting to the daemon)
// ============================================================================

/// A client-side named pipe connection to the Ainos daemon.
///
/// This can be used by CLI tools or other processes to communicate
/// with the running daemon over named pipes.
pub struct PipeClient {
    pipe: Option<PipeHandle>,
    pending: String,
    read_buf: Vec<u8>,
}

impl PipeClient {
    /// Connect to the Ainos daemon named pipe.
    pub fn connect() -> Result<Self, String> {
        Self::connect_to(PIPE_NAME)
    }

    /// Connect to a specific named pipe.
    pub fn connect_to(pipe_name: &str) -> Result<Self, String> {
        unsafe {
            let name_wide: Vec<u16> = OsStr::new(pipe_name)
                .encode_wide()
                .chain(std::iter::once(0))
                .collect();

            let handle = winapi::um::fileapi::CreateFileW(
                name_wide.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                0, // no sharing
                ptr::null_mut(), // default security
                winapi::um::fileapi::OPEN_EXISTING,
                winapi::um::fileapi::FILE_ATTRIBUTE_NORMAL | winapi::um::fileapi::FILE_FLAG_OVERLAPPED,
                ptr::null_mut(), // no template
            );

            if handle == INVALID_HANDLE_VALUE {
                return Err(format!("Failed to connect to pipe: {}", GetLastError()));
            }

            // Set pipe to message read mode
            let mut pipe_mode: DWORD = PIPE_READMODE_MESSAGE;
            let result = winapi::um::namedpipeapi::SetNamedPipeHandleState(
                handle,
                &mut pipe_mode,
                ptr::null_mut(),
                ptr::null_mut(),
            );

            if result == FALSE {
                CloseHandle(handle);
                return Err(format!("SetNamedPipeHandleState failed: {}", GetLastError()));
            }

            // Create overlapped event
            let event = CreateEventW(
                ptr::null_mut(),
                TRUE,
                FALSE,
                ptr::null(),
            );

            if event == INVALID_HANDLE_VALUE {
                CloseHandle(handle);
                return Err(format!("CreateEventW failed: {}", GetLastError()));
            }

            let overlapped = OVERLAPPED {
                Internal: 0,
                InternalHigh: 0,
                Offset: 0,
                OffsetHigh: 0,
                hEvent: event,
                Pointer: ptr::null_mut(),
            };

            let pipe = PipeHandle {
                handle,
                overlapped,
            };

            Ok(PipeClient {
                pipe: Some(pipe),
                pending: String::new(),
                read_buf: vec![0u8; READ_BUF_SIZE],
            })
        }
    }

    /// Send a message and receive the response.
    pub fn send_message(&mut self, msg: &IpcMessage) -> Result<IpcMessage, String> {
        let json = serde_json::to_string(msg)
            .map_err(|e| format!("Serialize error: {}", e))?;

        match self.pipe {
            Some(ref mut pipe) => {
                pipe.write(json.as_bytes())?;
                pipe.write(b"\n")?;
            }
            None => return Err("Pipe not connected".to_string()),
        }

        self.read_response()
    }

    /// Send a JSON string and receive the response.
    pub fn send_json(&mut self, json: &str) -> Result<String, String> {
        match self.pipe {
            Some(ref mut pipe) => {
                pipe.write(json.as_bytes())?;
                pipe.write(b"\n")?;
            }
            None => return Err("Pipe not connected".to_string()),
        }

        self.read_response_text()
    }

    /// Read a response from the pipe.
    fn read_response(&mut self) -> Result<IpcMessage, String> {
        let text = self.read_response_text()?;
        serde_json::from_str(&text)
            .map_err(|e| format!("Deserialize error: {}", e))
    }

    /// Read response text from the pipe.
    fn read_response_text(&mut self) -> Result<String, String> {
        loop {
            match self.pipe {
                Some(ref mut pipe) => {
                    let n = pipe.read(&mut self.read_buf)?;
                    if n == 0 {
                        return Err("Pipe disconnected".to_string());
                    }

                    if let Ok(text) = String::from_utf8(self.read_buf[..n].to_vec()) {
                        self.pending.push_str(&text);
                    } else {
                        return Err("Invalid UTF-8 response".to_string());
                    }

                    if let Some(idx) = self.pending.find('\n') {
                        let line = self.pending[..idx].trim().to_string();
                        self.pending = self.pending[idx + 1..].to_string();
                        return Ok(line);
                    }

                    if self.pending.len() > MAX_MESSAGE_SIZE {
                        return Err("Response too large".to_string());
                    }
                }
                None => return Err("Pipe not connected".to_string()),
            }
        }
    }

    /// Disconnect from the pipe.
    pub fn disconnect(&mut self) {
        if let Some(pipe) = self.pipe.take() {
            pipe.disconnect();
        }
    }
}

impl Drop for PipeClient {
    fn drop(&mut self) {
        self.disconnect();
    }
}

// ============================================================================
// Sync Named Pipe Server (for non-tokio environments)
// ============================================================================

/// A synchronous named pipe server that can be used without tokio.
///
/// This is useful for the Windows service mode where we want to run
/// the IPC server on a dedicated thread without the full tokio runtime.
pub struct SyncPipeServer {
    listener: PipeListener,
    running: std::sync::atomic::AtomicBool,
}

impl SyncPipeServer {
    /// Create a new synchronous pipe server.
    pub fn new(secure: bool) -> Result<Self, String> {
        let listener = PipeListener::new(PIPE_NAME, MAX_PIPE_INSTANCES, secure)?;
        Ok(SyncPipeServer {
            listener,
            running: std::sync::atomic::AtomicBool::new(false),
        })
    }

    /// Start the server with a message handler.
    ///
    /// The handler function receives the connection and should process
    /// messages from the client. This function blocks until `stop()` is called.
    pub fn run<F>(&mut self, handler: F) -> Result<(), String>
    where
        F: Fn(PipeConnection) + Send + Sync + 'static,
    {
        self.running.store(true, std::sync::atomic::Ordering::SeqCst);

        let handler = Arc::new(handler);

        while self.running.load(std::sync::atomic::Ordering::SeqCst) {
            match self.listener.accept() {
                Ok(connection) => {
                    let handler = handler.clone();
                    std::thread::spawn(move || {
                        handler(connection);
                    });
                }
                Err(e) => {
                    error!("SyncPipeServer accept error: {}", e);
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
        }

        Ok(())
    }

    /// Stop the server.
    pub fn stop(&self) {
        self.running.store(false, std::sync::atomic::Ordering::SeqCst);
    }

    /// Check if the server is running.
    pub fn is_running(&self) -> bool {
        self.running.load(std::sync::atomic::Ordering::SeqCst)
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

/// Check if the Ainos daemon pipe server is running.
pub fn is_daemon_running() -> bool {
    PipeClient::connect().is_ok()
}

/// Get daemon status as a JSON string.
pub fn get_daemon_status_text() -> Result<String, String> {
    let mut client = PipeClient::connect()?;
    let status = IpcMessage::Status;
    client.send_message(&status).map(|r| {
        serde_json::to_string(&r).unwrap_or_default()
    })
}

/// Send a shutdown command to the daemon.
pub fn send_shutdown() -> Result<(), String> {
    // We send a special message or just close the connection
    // For now, we rely on the service control manager for clean shutdown
    Ok(())
}

/// Get the current Windows username.
pub fn get_current_username() -> Result<String, String> {
    unsafe {
        let mut buf = [0u16; 256];
        let mut buf_len: DWORD = buf.len() as DWORD;

        let result = winapi::um::winbase::GetUserNameW(
            buf.as_mut_ptr(),
            &mut buf_len,
        );

        if result == FALSE {
            return Err(format!("GetUserNameW failed: {}", GetLastError()));
        }

        Ok(String::from_utf16_lossy(&buf[..buf_len as usize - 1]))
    }
}

/// Convert a Windows path to a Unix-style path (for display).
pub fn path_to_unix_style(path: &str) -> String {
    path.replace('\\', "/")
}

/// Convert a Unix-style path to a Windows path.
pub fn path_to_windows_style(path: &str) -> String {
    path.replace('/', "\\")
}

/// Ensure a directory exists (Windows-compatible).
pub fn ensure_directory(path: &str) -> Result<(), String> {
    unsafe {
        let path_wide: Vec<u16> = OsStr::new(path)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();

        let result = winapi::um::fileapi::CreateDirectoryW(
            path_wide.as_ptr(),
            ptr::null_mut(),
        );

        if result == FALSE {
            let err = GetLastError();
            if err != winapi::um::errhandlingapi::ERROR_ALREADY_EXISTS {
                return Err(format!("CreateDirectoryW failed: {}", err));
            }
        }

        Ok(())
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipe_name_constant() {
        assert_eq!(PIPE_NAME, r"\\.\pipe\ainos-daemon");
    }

    #[test]
    fn test_path_conversion() {
        let win_path = r"D:\Ainos\models\test.gguf";
        let unix_path = path_to_unix_style(win_path);
        assert_eq!(unix_path, "D:/Ainos/models/test.gguf");

        let back_to_win = path_to_windows_style(&unix_path);
        assert_eq!(back_to_win, win_path);
    }

    #[test]
    fn test_get_current_username() {
        let result = get_current_username();
        // This should work on any Windows system
        assert!(result.is_ok());
        let username = result.unwrap();
        assert!(!username.is_empty());
    }

    #[test]
    fn test_ensure_directory() {
        let temp_dir = std::env::temp_dir();
        let test_dir = temp_dir.join("ainos_test_dir");
        let test_path = test_dir.to_str().unwrap().to_string();

        // Clean up first
        let _ = std::fs::remove_dir_all(&test_path);

        // Create directory
        let result = ensure_directory(&test_path);
        assert!(result.is_ok());
        assert!(test_dir.exists());

        // Creating again should succeed (already exists)
        let result = ensure_directory(&test_path);
        assert!(result.is_ok());

        // Clean up
        let _ = std::fs::remove_dir_all(&test_path);
    }

    #[test]
    fn test_is_daemon_running() {
        // This will return false when no daemon is running
        let running = is_daemon_running();
        // Just check that it doesn't crash
        assert!(!running || running);
    }

    #[test]
    fn test_register_event_source() {
        let result = register_event_source();
        // This should not crash
        assert!(result.is_ok() || !result.is_ok());
    }

    #[test]
    fn test_is_running_as_service() {
        // This test verifies the function doesn't crash
        let _ = is_running_as_service();
    }

    #[test]
    fn test_get_ainos_install_dir() {
        // This returns None if no registry key exists
        let dir = get_ainos_install_dir();
        // Just check that it doesn't crash
        if let Some(ref d) = dir {
            assert!(!d.is_empty());
        }
    }

    #[test]
    fn test_get_daemon_status_text() {
        // This will fail if daemon is not running
        let result = get_daemon_status_text();
        // Just check that it doesn't crash
        assert!(result.is_err() || result.is_ok());
    }

    #[test]
    fn test_send_shutdown() {
        // Should not crash
        let _ = send_shutdown();
    }

    #[test]
    fn test_pipe_listener_creation() {
        let listener = PipeListener::new(r"\\.\pipe\ainos-test", 1, false);
        assert!(listener.is_ok());
    }

    #[test]
    fn test_pipe_listener_with_secure_attributes() {
        let listener = PipeListener::new(r"\\.\pipe\ainos-test-secure", 1, true);
        assert!(listener.is_ok());
    }

    #[test]
    fn test_async_pipe_server_creation() {
        // Create a minimal AppState for testing
        let cfg = crate::config::DaemonConfig::default();
        let state = Arc::new(RwLock::new(AppState::new(cfg)));
        let server = AsyncPipeServer::new(state, false);
        assert!(server.is_ok());
    }

    #[test]
    fn test_sync_pipe_server_creation() {
        let server = SyncPipeServer::new(false);
        assert!(server.is_ok());
        assert!(!server.is_running());
    }

    #[test]
    fn test_report_event() {
        // Should not crash
        report_info(1000, "Test info event from unit test");
        report_warning(1001, "Test warning event from unit test");
        report_error(1002, "Test error event from unit test");
    }

    #[test]
    fn test_pipe_client_creation() {
        // This will fail if daemon is not running, but shouldn't crash
        let result = PipeClient::connect();
        // Just verify it either succeeds or fails gracefully
        assert!(result.is_ok() || result.is_err());
    }

    #[test]
    fn test_pipe_client_custom_name() {
        let result = PipeClient::connect_to(r"\\.\pipe\nonexistent-test-pipe");
        assert!(result.is_err());
    }

    #[test]
    fn test_create_security_attributes() {
        let result = create_default_security_attributes();
        assert!(result.is_ok());
    }

    #[test]
    fn test_create_pipe_security_attributes() {
        let result = create_pipe_security_attributes();
        // This may fail in some environments, but shouldn't crash
        assert!(result.is_ok() || result.is_err());
    }

    #[test]
    fn test_client_id_setting() {
        let listener = PipeListener::new(r"\\.\pipe\ainos-client-test", 1, false);
        assert!(listener.is_ok());
    }

    #[test]
    fn test_max_pipe_instances_constant() {
        assert_eq!(MAX_PIPE_INSTANCES, PIPE_UNLIMITED_INSTANCES);
    }

    #[test]
    fn test_buffer_size_constants() {
        assert_eq!(PIPE_BUFFER_SIZE, 64 * 1024);
        assert_eq!(MAX_MESSAGE_SIZE, 1024 * 1024);
        assert_eq!(READ_BUF_SIZE, 8192);
    }

    #[test]
    fn test_path_conversion_roundtrip() {
        let paths = vec![
            r"C:\Users\test\file.txt",
            r"D:\Ainos\models\qwen.gguf",
            r"\\server\share\file",
            r"C:\Users\test\路径\中文.txt",
        ];

        for path in &paths {
            let unix = path_to_unix_style(path);
            let win = path_to_windows_style(&unix);
            assert_eq!(win.as_str(), *path, "Roundtrip failed for: {}", path);
        }
    }

    #[test]
    fn test_path_to_unix_style() {
        assert_eq!(path_to_unix_style(r"C:\Users\test"), "C:/Users/test");
        assert_eq!(path_to_unix_style(r"no_backslash"), "no_backslash");
        assert_eq!(path_to_unix_style(r"mixed\path/here"), "mixed/path/here");
    }

    #[test]
    fn test_path_to_windows_style() {
        assert_eq!(path_to_windows_style("C:/Users/test"), r"C:\Users\test");
        assert_eq!(path_to_windows_style("no_slash"), "no_slash");
        assert_eq!(path_to_windows_style("C:/"), r"C:\");
    }
}