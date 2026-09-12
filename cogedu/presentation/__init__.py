"""cogedu.presentation — 呈现引擎（Phase 1 新写，非内核复制）.

两阶段生成：intervention（LCA 输出）→ 大纲（Outline）→ 场景（Scene）。

包边界（方案文档 13.2 1-A-3 / 1-A-5，红线级别约定）：

1. 本包对内核是**只读**的：唯一允许的内核入口是 ``cogedu.runtime.api``
   （plan / update_belief 等），禁止 import ``cogedu.cta`` / ``cogedu.lca``
   / ``cogedu.evidence`` 等内核内部类来读写学生认知状态。场景/大纲与
   ``Goal``/``Evidence`` 的关联只存 **引用 ID**（intervention_id /
   goal_id / evidence_id），不拷贝对象。
2. 本包**不依赖 web 层**：LLM client 由调用方在构造时注入（FastAPI
   装配传 ``web.api.llm.get_llm()``，测试注入 mock）。依赖方向永远是
   web → presentation，不允许反向。
3. 本包纳入 ``scripts/check_no_direct_state_mutation.py`` 扫描范围
   （githooks pre-commit / pre-push 强制执行）。
"""
