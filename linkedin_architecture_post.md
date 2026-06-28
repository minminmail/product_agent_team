# LinkedIn post — Architecture evolution (before / after)

Attach the matching image: `architecture_before_after_en.png` (English) or `architecture_before_after_cn.png` (Chinese).

---

## English

From a monolith to orchestrated agents 🧭

I refactored **Marketing Agent Team** from a single, tightly-coupled pipeline into an orchestrated, decoupled multi-agent system.

**Before:** one agent ran everything in a single pass — research and supplier sourcing fused together. Hard to reuse, and you couldn't run a stage on its own.

**After:**
• **Amanda** orchestrates the whole run end-to-end
• **Maria** (product research) and **Javier** (supplier sourcing) are now independent agents that hand off through a saved `predictions.json`
• a conditional **LangGraph** pipeline (only source suppliers if research found products)
• a live web dashboard with email login

Same outcome — winning products + vetted, EU-certified suppliers — but now modular, observable, and easy to extend.

Before / after architecture 👇

#AIAgents #LangGraph #SoftwareArchitecture #AI #MultiAgent #BuildInPublic

---

## 中文

从单体到编排式多智能体 🧭

我把「营销智能体团队」从一条紧耦合的流水线，重构为编排式、解耦的多智能体系统。

**改造前：** 一个智能体在一次运行里完成所有事——选品与供应商寻源揉在一起，难以复用，也无法单独运行某个阶段。

**改造后：**
• **Amanda** 负责端到端编排
• **Maria**（选品）与 **Javier**（供应商寻源）成为相互独立的智能体，通过保存的 `predictions.json` 完成交接
• 条件式 **LangGraph** 流水线（只有研究阶段找到产品，才进入寻源）
• 带邮箱登录的实时网页面板

结果不变——找到潜力产品 + 甄选通过欧盟认证的供应商——但更模块化、可观测、易扩展。

架构改造前后对比 👇

#AI智能体 #LangGraph #软件架构 #多智能体
