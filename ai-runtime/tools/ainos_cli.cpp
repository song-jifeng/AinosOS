// Ainos OS - CLI 工具库
// 提供命令行交互功能

#include "ainos/ai_runtime.h"
#include <iostream>
#include <string>
#include <vector>

namespace ainos {
namespace tools {

/// 打印 AI Runtime 版本信息
void PrintVersion() {
    std::cout << "Ainos AI Runtime v" << ainos::ai::AI_RUNTIME_VERSION << std::endl;
    std::cout << "Ainos OS - AI Native Operating System" << std::endl;
}

/// 打印帮助信息
void PrintHelp() {
    std::cout << "Ainos OS CLI Tools" << std::endl;
    std::cout << "Usage:" << std::endl;
    std::cout << "  ainos-cli status          - 查看系统状态" << std::endl;
    std::cout << "  ainos-cli models          - 列出已加载模型" << std::endl;
    std::cout << "  ainos-cli infer <prompt>  - 执行推理" << std::endl;
    std::cout << "  ainos-cli version         - 显示版本信息" << std::endl;
}

} // namespace tools
} // namespace ainos