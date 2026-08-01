# Ainos OS Default AI Security Policy
# 四层架构: system -> user -> app -> session

layer system {
    allow ai_model_load;
    deny kernel_module_load;
    deny hardware_access;
}

layer user {
    allow data_access if user_role == "admin";
    deny data_access if user_role == "guest";
    allow telemetry_upload;
}

layer app {
    deny network_access if app_id == "untrusted_ai";
    allow gpu_compute if app_id == "verified_ai";
    ask file_write;
}

layer session {
    ask ai_model_load if session_type == "remote";
    deny hardware_access if session_type == "untrusted";
}