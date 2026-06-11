# 云端共享版视觉代理部署说明

本文用于把浏览器插件的视觉复核能力部署成 3-5 个业务同事可共享的云端服务。插件不保存 Ark/Doubao 模型 Key，Key 只放在云服务器环境变量中。

## 架构

```text
业务同事 Chrome 插件
  -> HTTPS /api/review/vision
  -> 云端 FastAPI 视觉代理
  -> Ark/Doubao Responses API
  -> 插件侧边栏展示视觉识别结果
```

## 推荐云资源

- 腾讯云轻量应用服务器或阿里云轻量应用服务器
- Ubuntu 22.04/24.04
- 1 核 1G 起步即可，建议 1 核 2G
- 开放端口：`80`、`443`

## 服务端配置

云服务器上只需要运行 UI 服务中的复核接口：

- `GET /api/review/health`
- `POST /api/review/vision`

不要把 `ARK_API_KEY` 写进插件或 Git。

在服务器创建 `/opt/precision-marketing-auto/.env.cloud`：

```bash
ARK_API_KEY=你的 Ark Key
ARK_VISION_MODEL=doubao-seed-2-0-lite-260428
```

## 部署步骤

以下命令在云服务器执行。

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin pmreview
sudo mkdir -p /opt/precision-marketing-auto
sudo chown -R pmreview:pmreview /opt/precision-marketing-auto
```

上传或 clone 项目到 `/opt/precision-marketing-auto` 后：

```bash
cd /opt/precision-marketing-auto
sudo -u pmreview python3 -m venv .venv
sudo -u pmreview .venv/bin/python -m pip install -U pip
sudo -u pmreview .venv/bin/python -m pip install -r requirements-ui.txt
```

写入 `.env.cloud`：

```bash
sudo tee /opt/precision-marketing-auto/.env.cloud >/dev/null <<'EOF'
ARK_API_KEY=你的 Ark Key
ARK_VISION_MODEL=doubao-seed-2-0-lite-260428
EOF
sudo chmod 600 /opt/precision-marketing-auto/.env.cloud
sudo chown pmreview:pmreview /opt/precision-marketing-auto/.env.cloud
```

安装 systemd 服务：

```bash
sudo cp /opt/precision-marketing-auto/deploy/review-proxy.service /etc/systemd/system/review-proxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now review-proxy
sudo systemctl status review-proxy
```

本机健康检查：

```bash
curl http://127.0.0.1:8790/api/review/health
```

## Nginx 和 HTTPS

安装 Nginx：

```bash
sudo apt update
sudo apt install -y nginx
```

复制模板并修改域名：

```bash
sudo cp /opt/precision-marketing-auto/deploy/nginx-review-proxy.conf /etc/nginx/sites-available/review-proxy
sudo sed -i 's/review.example.com/你的域名/g' /etc/nginx/sites-available/review-proxy
sudo ln -sf /etc/nginx/sites-available/review-proxy /etc/nginx/sites-enabled/review-proxy
sudo nginx -t
sudo systemctl reload nginx
```

配置 HTTPS。已有域名时推荐 Certbot：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

公网健康检查：

```bash
curl https://你的域名/api/review/health
```

## 插件配置

同事安装插件后，在侧边栏填写：

- 视觉服务地址：`https://你的域名`

之后 DOM 复核在浏览器本地完成，只有手动点击“截图复核”时才会截图并调用云端模型。

## 安全和费用控制

- `ARK_API_KEY` 只放服务器 `.env.cloud`，不要写进插件。
- 当前插件单页最多调用 3 次视觉复核。
- 服务端限制 data URL 截图大小为 8MB。
- 后续如使用人数增加，应增加调用日志、内网或网关访问控制、每日预算上限。

## 常见问题

- `503 未配置 ARK_API_KEY`：服务器环境变量未加载，检查 `systemctl status review-proxy` 和 `.env.cloud`。
- 视觉接口超时：检查服务器能否访问 `https://ark.cn-beijing.volces.com`。
- 插件请求失败：确认插件视觉服务地址不要写 `/api/review/vision` 以外的错误路径；写根地址 `https://你的域名` 即可。
