# ----------------------------------------------------------------------
# 项目检查入口：业务测试、Python 编译检查和 JavaScript 语法检查各解决不同问题。
# 语法正确不代表业务正确，所以测试会覆盖版本切换、删除、引用与失败场景。
# 用法示例：powershell -File scripts/check.ps1
# 面试问：退出码为什么要检查？答：外部命令失败未必触发 PowerShell 异常，需要主动中止。
# ----------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force data/tmp | Out-Null
$env:TEMP = Join-Path $PWD 'data/tmp'
$env:TMP = $env:TEMP
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& ./.venv/Scripts/python.exe -m pytest --basetemp=data/pytest-tmp
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& ./.venv/Scripts/python.exe -m compileall -q app scripts
if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed.' }
node --check web/app.js
if ($LASTEXITCODE -ne 0) { throw 'JavaScript syntax check failed.' }
