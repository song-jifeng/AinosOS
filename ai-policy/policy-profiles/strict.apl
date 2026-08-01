# Ainos OS Strict Mode Policy
layer system {
    deny *; # 默认拒绝所有系统级操作
    allow ai_model_load if context == "signed_binary";
}

layer user {
    deny *;
    allow data_access if user_role == "root";
}

layer app {
    deny *;
    allow gpu_compute if app_id == "system_ai";
}

layer session {
    deny *;
    allow * if session_type == "local_secure";
}