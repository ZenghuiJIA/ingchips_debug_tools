# HILI 固件插桩示例

`firmware/hil-instrumentation` 是不依赖芯片 HAL 的静态 C 核心。平台端口必须提供时间源、扩展计数、临界区和整帧发送；示例不写死 UART、RTT、链接地址或寄存器。`HIL_INSTRUMENTATION_DISABLED` 下宏不求值。

主机协议为 HILI v1，小端、40 字节头、最大 payload 1024 字节、CRC-32/ISO-HDLC。真实固件接入前，需要确定 MCU、编译器、优化等级、时钟和保留区；普通 RAM 不等于断电保存。

主机可用 `hil-protocol.exe` 的 `hili_configure/hili_feed/hili_finish` 解析二进制或 `@HILI1 <base64>\n` 文本封装。跨语言固定向量和上板开销应在目标工程验收。
