# SpiderMap - Google Maps 商家信息采集工具

一个基于Python的Google Maps商家信息采集工具，支持Web界面操作，可提取商家名称、地址、电话、网站等信息。

## 功能特性

- 🌍 支持全球地区搜索
- 🏪 灵活的商品类别搜索
- 📱 提取商家电话、地址、网站等关键信息
- 💻 简洁的Web操作界面
- 📊 支持Excel和CSV格式导出
- ☁️ 支持云端部署

## 技术架构

- **后端**: FastAPI + Python
- **爬虫引擎**: Playwright (Chromium)
- **前端**: HTML + CSS + JavaScript
- **数据格式**: Excel (.xlsx) / CSV
- **部署**: Render (免费云服务)

## 快速开始

### 本地运行

1. 克隆仓库
```bash
git clone https://github.com/xhlhub/spiderMap.git
cd spiderMap
```

2. 安装依赖
```bash
pip install -r requirements.txt
python -m playwright install chromium --with-deps
```

3. 启动服务
```bash
uvicorn app:app --reload --port 8000
```

4. 访问 http://localhost:8000

### 云端部署

1. Fork本仓库到你的GitHub账号
2. 在 [Render](https://render.com) 创建新的Web Service
3. 连接你的GitHub仓库
4. 使用以下配置：
   - **Build Command**: `pip install -r requirements.txt && python -m playwright install chromium --with-deps`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## 使用方法

1. 在Web界面输入：
   - **地点**: 如"洛杉矶"、"New York"
   - **店铺类型**: 如"修车店"、"restaurant"
   - **采集条数**: 1-300条

2. 点击"开始采集"，等待结果

3. 查看采集结果，支持下载Excel或CSV格式

## 注意事项

- 请遵守Google Maps的使用条款
- 建议采集条数控制在100条以内，避免触发反爬机制
- 如遇到验证码，请降低采集条数或等待一段时间后重试
- 云端部署默认使用无头浏览器模式

## 项目结构

```
spiderMap/
├── app.py              # FastAPI主应用
├── gmaps_scraper.py    # 爬虫核心逻辑
├── templates/          # HTML模板
│   ├── index.html      # 首页
│   └── results.html    # 结果页
├── requirements.txt    # Python依赖
├── render.yaml         # Render部署配置
└── README.md          # 项目说明
```

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

---

**免责声明**: 本工具仅供学习和研究使用，请遵守相关网站的使用条款和法律法规。 