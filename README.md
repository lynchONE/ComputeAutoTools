# Compute Auto Tools

Compute Auto Tools 是一个本地 Web 控制台，用已配置的平台适配器定时扫描 GPU 报价，按条件过滤机器，按性价比排序，并可在命中后自动创建实例、测试 SSH 连通性、通过 Bark 通知用户。

## 功能

- 指定 GPU 型号、GPU 数量、价格上限、总 TFLOPS、TFLOPS/USD、可靠性、显存等条件。
- 默认按 `total_flops / dph_total` 本地排序，也支持价格、总 TFLOPS、可靠性等排序。
- 前端保存所有配置到 `data/config.json`。
- 支持手动扫描和后台定时扫描。
- 自动创建默认关闭。开启后会受 `max_created_instances` 和 `max_creates_per_cycle` 限制。
- 创建后轮询实例详情，拿到 SSH host/port 后做 TCP 或 SSH 命令测试。
- 创建并连通后发送 Bark 通知。

## 安装

```powershell
py -m pip install -r requirements.txt
```

## 启动

```powershell
py main.py --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765
```

## 使用建议

1. 先选择平台，填写对应 API Key 和扫描条件。
2. 保持“命中后自动创建”关闭，点击“手动扫描”，确认候选机器排序和价格符合预期。
3. 配好 Docker image、磁盘、连接测试和 Bark。
4. 点击“测试 Bark”确认通知可用。
5. 再开启“命中后自动创建”并启动监控。

## Bark URL

支持两种格式：

```text
https://api.day.app/YOUR_KEY
https://api.day.app/YOUR_KEY/{title}/{body}
```

第二种格式会替换 `{title}` 和 `{body}`。

## Vast SDK 映射

搜索使用：

```python
VastAI.search_offers(query=..., type=..., order=..., limit=..., storage=..., no_default=True)
```

创建使用：

```python
VastAI.create_instance(id=offer_id, image=..., disk=..., label=..., env=..., runtype=...)
```

Vast 官方 query 字段包括 `gpu_name`、`num_gpus`、`dph_total` alias `dph`、`total_flops`、`flops_per_dphtotal` alias `flops_usd`、`reliability`、`gpu_ram` 等。

## 注意

- `data/config.json` 包含 API key，已被 `.gitignore` 排除。
- 自动创建会真实租用平台机器，建议先用手动扫描验证条件。
- TCP 测试只证明 SSH 端口可达；需要验证登录和密钥时，把连接测试模式改成 `ssh`。
