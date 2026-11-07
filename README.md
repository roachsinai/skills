# skills

个人 [DSH（DeepSeek Harness）](https://github.com/deepseek-ai) skill 集合。

把本仓库根目录加入 DSH 的 customSkillDirs（`@deepseek-ai/dsh-skill-filesystem` 配置），其中的 skill 即可在所有会话中自动发现使用，无需重启：

```yaml
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'
  config:
    customSkillDirs:
      - ~/code/repos/skills
```

## Skills

| Skill | 说明 |
|---|---|
| [zhihu-markdown](zhihu-markdown/) | 抓取知乎回答/专栏文章并转为离线 Markdown 文档（图片本地化、代码块、公式、完整性校验），内置反爬方法链与失效自更新协议 |
