# AGENTS.md

本项目的 agent / 开发指引**统一维护在 [CLAUDE.md](CLAUDE.md)**，本文件仅作入口，不再保留全文副本（此前两份全文并存已出现内容漂移）。

**请先阅读 [CLAUDE.md](CLAUDE.md)** — 包含项目概述、架构说明、线程模型、配置开关、开发规范、测试框架与常见问题。

## ⚠️ 关键约束速览 - 违反将导致系统故障

完整说明见 [CLAUDE.md](CLAUDE.md) 的「关键约束」章节：

1. **配置集中管理**: 所有可配置参数在 [config.py](config.py) 中，严禁硬编码魔法数字
2. **模拟交易优先**: 测试新功能前必须设置 `ENABLE_SIMULATION_MODE = True`
3. **线程安全**: 修改共享数据必须使用 `threading.Lock()` 保护
4. **信号验证**: 交易信号必须经过 `validate_trading_signal()` 验证，防止重复执行
5. **双层存储同步**: 修改内存数据库后必须调用 `_increment_data_version()`
6. **线程注册规范**: 注册线程监控时必须使用 `lambda` 获取线程对象
7. **Git操作**: 除非用户明确要求，不要主动执行 git 提交和分支操作

## 其他入口

- **[README.md](README.md)** — 项目总览、功能特性、快速开始
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — 系统架构、数据流、数据库设计
- **[QUICK_START.md](QUICK_START.md)** — 快速入门指南
- **[CHANGELOG.md](CHANGELOG.md)** — 版本变更日志
- **[在线文档站](https://weihong-su.github.io/miniQMT/)** — 完整文档（源码在 `docs/site/`）

---

**ALWAYS RESPOND IN SIMPLIFIED CHINESE!!!**
