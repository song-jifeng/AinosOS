/*
 * AinosOS - errno.h
 * Error code definitions
 */

#ifndef AINOS_ERRNO_H
#define AINOS_ERRNO_H

/* Success */
#define EOK                 0

/* Generic / unknown error */
#define EUNKNOWN            1
#define EFAIL               1

/* Argument errors */
#define EINVAL              2       /* Invalid argument */
#define EFAULT              3       /* Bad address */
#define E2BIG               4       /* Argument list too long */
#define ENOMEM              5       /* Out of memory */
#define EACCES              6       /* Permission denied */
#define EPERM               7       /* Operation not permitted */
#define ENOSYS              8       /* Function not implemented */
#define EBUSY               9       /* Resource busy */
#define EEXIST              10      /* File exists */
#define ENOENT              11      /* No such file or directory */
#define ENOTDIR             12      /* Not a directory */
#define EISDIR              13      /* Is a directory */
#define EMFILE              14      /* Too many open files */
#define ENFILE              15      /* File table overflow */
#define EPIPE               16      /* Broken pipe */
#define EAGAIN              17      /* Try again */
#define EWOULDBLOCK         EAGAIN
#define EINTR               18      /* Interrupted system call */
#define EIO                 19      /* I/O error */
#define ENXIO               20      /* No such device or address */
#define EOVERFLOW           21      /* Value too large */
#define ESPIPE              22      /* Illegal seek */
#define ERANGE              23      /* Result too large */
#define EDOM                24      /* Domain error */
#define EDEADLK             25      /* Resource deadlock avoided */
#define ENOTTY              26      /* Not a typewriter */
#define ETIME               27      /* Timer expired */
#define ENODATA             28      /* No data available */
#define ECONNRESET          29      /* Connection reset */
#define ECONNREFUSED        30      /* Connection refused */
#define EALREADY            31      /* Already connected */
#define ENOPROTOOPT         32      /* Protocol not available */
#define ENOTSOCK            33      /* Not a socket */
#define EMSGSIZE            34      /* Message too long */
#define EAFNOSUPPORT        35      /* Address family not supported */
#define EADDRINUSE          36      /* Address already in use */
#define EADDRNOTAVAIL       37      /* Address not available */
#define ENETDOWN            38      /* Network is down */
#define ENETUNREACH         39      /* Network unreachable */
#define EHOSTDOWN           40      /* Host is down */
#define EHOSTUNREACH        41      /* Host unreachable */
#define ESHUTDOWN           42      /* Cannot send after transport endpoint shutdown */
#define ETIMEDOUT           43      /* Connection timed out */
#define ENOTCONN            44      /* Transport endpoint not connected */

/* Filesystem-specific */
#define ENOBUFS             45      /* No buffer space available */
#define ENODEV              46      /* No such device */
#define ENOTEMPTY           47      /* Directory not empty */
#define EROFS               48      /* Read-only filesystem */
#define EFBIG               49      /* File too large */
#define ENOSPC              50      /* No space left on device */
#define EMLINK              51      /* Too many links */
#define ENAMETOOLONG        52      /* File name too long */
#define EDQUOT              53      /* Disk quota exceeded */

/* Device-specific */
#define EIOCTL              54      /* Invalid ioctl */
#define EBDADDR             55      /* Bad block address */
#define EMEDIA              56      /* Media error */
#define ENOMEDIUM           57      /* No medium found */
#define EMEDIUMTYPE         58      /* Wrong medium type */

/* Thread/scheduler */
#define ESRCH               59      /* No such process */
#define EDEADLOCK           60      /* Deadlock */
#define ENOTRECOVERABLE     61      /* State not recoverable */
#define EOWNERDEAD          62      /* Previous owner died */

/* Convert errno to string */
const char *strerror(int errnum);

#endif /* AINOS_ERRNO_H */