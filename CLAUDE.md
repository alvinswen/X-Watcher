# AI-DLC and Spec-Driven Development

Kiro-style Spec Driven Development implementation on AI-DLC (AI Development Life Cycle)

## Development Methodology

This project follows Spec-Driven Development (SDD) with TDD. Always follow the full spec lifecycle: init → requirements → gap analysis → design → validation → task generation → approval → implementation. Never skip to implementation without approved specs and tasks.

## Platform & Environment
- This is a **Windows** development environment. Use Windows-compatible commands (e.g., `taskkill` not `kill`, `dir` not `ls`).
- Always stop running services (uvicorn, etc.) before running database migrations or operations that require DB locks.
- After code changes, manually restart uvicorn — `--reload` is unreliable. Kill stale uvicorn processes before starting new ones.

### 进程与端口管理最佳实践（Windows + Git Bash 环境）

**启动服务时：**
- 启动 uvicorn 后立即用 `ps -W | grep python` 记录其 **WINPID**（第 4 列），后续终止时直接用此 PID
- 示例：`python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 &` 然后 `ps -W | grep uvicorn`

**终止服务时（按优先级顺序）：**
1. **首选：PowerShell `Stop-Process`**（避免 Git Bash 的 MSYS 路径转换问题）
   ```powershell
   powershell -Command "Stop-Process -Id <WINPID> -Force"
   ```
2. **如果不知道 PID，先精确定位：**
   ```bash
   # 查看端口占用（获取 OwningProcess PID）
   powershell -Command "Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess"
   # 查看所有 Python 进程的 WINPID 和命令行
   ps -W | grep python
   ```
3. **netstat 显示的 PID 可能是已退出的父进程**——如果 `Stop-Process` 报"找不到进程"，
   说明真正持有端口的是其 multiprocessing 子进程。用 `ps -W | grep python` 查找仍存活的子进程 WINPID 并终止
4. **最后手段：终止所有 Python 进程**（会影响 nanobot 等其他服务）
   ```powershell
   powershell -Command "Get-Process python | Stop-Process -Force"
   ```

**Git Bash 中的 Windows 命令注意事项：**
- `taskkill /F /PID` 在 Git Bash 中 `/F` 会被 MSYS2 转为路径 `F:/`，导致命令静默失败
- 必须用 `taskkill //F //PID` 双斜杠，或直接用 PowerShell
- `tasklist /FI` 同理，`/FI` 也会被转换。始终优先使用 PowerShell
- PowerShell 内联命令中 `$` 变量会被 bash 的 extglob 替换——如需使用复杂 PowerShell 脚本，写入 `.ps1` 文件再执行：`powershell -ExecutionPolicy Bypass -File script.ps1`
- PowerShell 脚本中不要用 `$pid` 作为变量名（PowerShell 内置只读变量）

## Project Context

### Paths
- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`

### Steering vs Specification

**Steering** (`.kiro/steering/`) - Guide AI with project-wide rules and context
**Specs** (`.kiro/specs/`) - Formalize development process for individual features

### Active Specifications
- Check `.kiro/specs/` for active specifications
- Use `/kiro:spec-status [feature-name]` to check progress

## Development Guidelines
- Think in English, generate responses in Simplified Chinese. All Markdown content written to project files (e.g., requirements.md, design.md, tasks.md, research.md, validation reports) MUST be written in the target language configured for this specification (see spec.json.language).

## Minimal Workflow
- Phase 0 (optional): `/kiro:steering`, `/kiro:steering-custom`
- Phase 1 (Specification):
  - `/kiro:spec-init "description"`
  - `/kiro:spec-requirements {feature}`
  - `/kiro:validate-gap {feature}` (optional: for existing codebase)
  - `/kiro:spec-design {feature} [-y]`
  - `/kiro:validate-design {feature}` (optional: design review)
  - `/kiro:spec-tasks {feature} [-y]`
- Phase 2 (Implementation): `/kiro:spec-impl {feature} [tasks]`
  - `/kiro:validate-impl {feature}` (optional: after implementation)
- Progress check: `/kiro:spec-status {feature}` (use anytime)

## Development Rules
- 3-phase approval workflow: Requirements → Design → Tasks → Implementation
- Human review required each phase; use `-y` only for intentional fast-track
- Keep steering current and verify alignment with `/kiro:spec-status`
- Follow the user's instructions precisely, and within that scope act autonomously: gather the necessary context and complete the requested work end-to-end in this run, asking questions only when essential information is missing or the instructions are critically ambiguous.

## Steering Configuration
- Load entire `.kiro/steering/` as project memory
- Default files: `product.md`, `tech.md`, `structure.md`
- Custom files are supported (managed via `/kiro:steering-custom`)
