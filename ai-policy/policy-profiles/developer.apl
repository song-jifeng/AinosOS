# Ainos OS Developer Mode Policy
layer system {
    allow *;
}

layer user {
    allow *;
}

layer app {
    allow *;
}

layer session {
    allow *;
    # 仅记录审计日志，不阻断
}