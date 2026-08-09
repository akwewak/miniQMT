# 常见问题

## Q: 服务启动后账号 `connected: false`？

- 检查 `qmt_path` 是否指向正确的 `userdata_mini` 目录
- 确认 QMT 客户端已启动并登录对应账号
- 等待约 30 秒，HealthMonitor 会自动重试连接
- 查看日志获取详细错误：`xqm_manager.bat logs`

---

## Q: 网页测试界面发请求报"Network Error"？

**原因**：浏览器从 `file://` 打开 HTML 时，CORS 策略会阻止向 `http://` 发起请求。

**解决**：服务已内置 `CORSMiddleware allow_origins=*`，确认服务已启动即可。

验证 CORS 是否生效：

```bash
curl -s -I -X OPTIONS "http://127.0.0.1:8888/api/v1/accounts" \
  -H "Origin: null" -H "Access-Control-Request-Method: POST" \
  | grep -i access-control
# 期望: access-control-allow-origin: *
```

---

## Q: 所有接口返回 401？

- 服务配置了 `api_token`，需在请求头中加 `X-API-Token: <token>`
- `GET /api/v1/health` 免 Token 可达，可先用它验证服务是否在线（但不带 Token 时不返回 `accounts` 明细）
- 网关所有数据端点（含 `/api/positions` 等只读端点）都需要 Token，这是有意为之：只读端点会返回持仓成本与盈亏明细
- 若配置了反向代理且确认请求来自本机却仍 401，检查是否需要开启 `trust_proxy`（默认 `false`，网关不信任 `X-Forwarded-For`）

---

## Q: 多账号时某账号断线，其他账号受影响吗？

不受影响。每个账号有独立的连接实例，断线不传染。

---

## Q: 如何不重启服务临时增加账号？

```bash
curl -X POST http://127.0.0.1:8888/api/v1/accounts \
  -H "Content-Type: application/json" \
  -d '{"account_id":"55009641","qmt_path":"C:/QMT1/userdata_mini"}'
```

---

## Q: `position()` 返回空 DataFrame？

1. 确认 `connected: true`（`GET /accounts/{id}/status`）
2. 查看 `/metrics/{id}` 中 `query_positions` 的 `error_calls`
3. 确认账号下确实有持仓

---

## Q: xqm_manager.bat 在 Git Bash 中报 `timeout` 错误？

Git Bash 的 `timeout` 命令语法与 Windows cmd 不同，导致语法错误，但服务功能正常。请在 `cmd.exe` 或 PowerShell 中运行该脚本。

---

## Q: GitHub Pages 文档没有更新？

1. 检查 GitHub Actions 是否已触发：仓库 → Actions → Deploy Docs to GitHub Pages
2. 确认修改了 `docs/xqm/` 或 `mkdocs.yml` 中的文件
3. 手动触发：Actions 页面 → 选择工作流 → Run workflow
