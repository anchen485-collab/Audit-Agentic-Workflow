from typing import Any

from pydantic import BaseModel, Field

from app.domain.decisions import DecisionAction, DecisionStatus


class CurrentUser(BaseModel):
    """当前登录用户：用于认证、角色权限和租户隔离。"""

    user_id: str = Field(description="用户 ID，来自企业认证系统或本地 token 映射")
    tenant_id: str = Field(description="租户 ID，用于隔离不同组织的数据")
    roles: list[str] = Field(default_factory=list, description="用户角色，例如 uploader、reviewer、admin、auditor")

    def has_role(self, role: str) -> bool:
        """判断用户是否拥有指定角色；admin 默认拥有全部权限。"""
        return "admin" in self.roles or role in self.roles

    def has_any_role(self, roles: set[str]) -> bool:
        """判断用户是否拥有任意一个指定角色。"""
        return "admin" in self.roles or bool(set(self.roles) & roles)


class AuditCase(BaseModel):
    """审批单：表示员工 Excel 中的一条录入记录。"""

    case_id: str = Field(description="审批单唯一 ID，用来追踪单条记录")
    batch_id: str = Field(description="批次 ID，同一次 Excel 上传生成的记录共享同一个批次")
    row_number: int = Field(description="原始 Excel 行号，方便回查是哪一行数据")
    employee_name: str = Field(description="录入员工姓名，用于人员汇总和质量统计")
    company_raw: str = Field(description="Excel 中原始企业字段，可能包含企业名和官网链接")
    company_name: str = Field(description="清洗后的企业名称，用于查询证据和展示结果")
    website_url: str = Field(default="", description="企业官网链接，后续官网爬虫会基于它采集证据")
    entered_level1: str = Field(description="员工录入的一级分类")
    entered_level2: str = Field(default="", description="员工录入的二级分类，没有填写时为空")
    entered_subcategory: str = Field(description="员工录入的细分类别，可能对应内部二级或三级分类")
    entered_stage: str = Field(default="", description="员工录入的业务环节，首版可记录但不作为核心判断依据")
    status: str = Field(default="pending", description="当前处理状态，例如 pending、processing、completed")


class EvidenceSnippet(BaseModel):
    """证据片段：表示某个来源中的一段可解释证据。"""

    source: str = Field(description="证据来源，例如 mock_company_provider、website、qichacha")
    text: str = Field(description="具体证据文本，例如官网简介中的一句业务描述")
    url: str = Field(default="", description="证据对应的页面 URL，mock 数据可以为空")


class EvidencePackage(BaseModel):
    """证据包：表示系统为某条审批单采集到的外部证据。"""

    case_id: str = Field(description="证据所属的审批单 ID")
    company_name: str = Field(description="证据对应的企业名称")
    sources: list[str] = Field(default_factory=list, description="本次证据采集使用到的来源列表")
    business_scope: str = Field(default="", description="汇总后的企业业务描述，用于规则匹配和 LLM 语义判断")
    snippets: list[EvidenceSnippet] = Field(
        default_factory=list,
        description="可解释的证据片段列表，用于 trace、导出和人工复核",
    )
    quality_score: int = Field(ge=0, le=100, description="证据质量分，0 表示没有有效证据，100 表示证据充分")
    errors: list[str] = Field(default_factory=list, description="证据采集中的错误信息")


class CategoryRule(BaseModel):
    """内部分类规则：表示一条可被召回的分类规则。"""

    level1: str = Field(description="内部规则的一级分类")
    level2: str = Field(description="内部规则的二级分类")
    level3: str = Field(description="内部规则的三级分类")
    module: str = Field(description="规则所属模块，例如业务领域、经典案例、产品服务")
    keywords: list[str] = Field(default_factory=list, description="该规则下可用于召回或匹配的关键词")


class CandidateCategory(BaseModel):
    """分类候选：支持员工细分命中二级或三级两种粒度。"""

    level1: str = Field(description="候选分类的一级分类")
    level2: str = Field(description="候选分类的二级分类")
    level3: str = Field(default="", description="候选分类的三级分类；二级候选时为空")
    granularity: str = Field(description="候选粒度：level2 或 level3")
    matched_entered_value: str = Field(description="员工细分单元格中命中的原始值")
    child_count: int = Field(default=0, description="二级候选下去重后的三级子类数量")
    children: list[CategoryRule] = Field(default_factory=list, description="二级候选下聚合的三级规则")
    keywords: list[str] = Field(default_factory=list, description="候选分类聚合后的业务关键词")


class CandidateRuleSet(BaseModel):
    """候选规则集：用于约束 LLM 只能基于候选分类判断。"""

    case_id: str = Field(description="候选规则所属的审批单 ID")
    entered_path_exists: bool = Field(description="员工录入的分类路径是否存在于内部规则表")
    candidates: list[CategoryRule] = Field(default_factory=list, description="召回出来的 Top-K 候选规则")
    retrieval_reason: str = Field(default="", description="召回原因说明，例如命中分类名、关键词或外部证据")
    recall_default_top_k: int = Field(default=5, description="本次召回使用的默认候选数量")
    recall_max_top_k: int = Field(default=8, description="本次召回允许的最大候选数量")
    raw_match_count: int = Field(default=0, description="去重前命中的规则条目数量")
    deduped_match_count: int = Field(default=0, description="按分类路径去重后的命中数量")
    exact_match_count: int = Field(default=0, description="员工录入细分精确命中的候选数量")
    truncated: bool = Field(default=False, description="候选规则是否因为最大数量限制被截断")
    category_candidates: list[CandidateCategory] = Field(
        default_factory=list,
        description="支持二级和三级粒度的分类候选，供下游 Agent 优先使用",
    )
    entered_subcategory_granularity: str = Field(
        default="unknown",
        description="员工细分字段识别出的粒度：level2、level3、mixed、ambiguous、unknown",
    )
    granularity_reason: str = Field(default="", description="细分粒度识别原因")
    unmatched_values: list[str] = Field(default_factory=list, description="未命中规则库的员工细分值")
    ambiguous_values: list[str] = Field(default_factory=list, description="存在多个可能路径的员工细分值")


class AgentAssessment(BaseModel):
    """Agent 判断结果：统一记录每个 Agent 的输出、置信度和耗时。"""

    agent_name: str = Field(description="Agent 名称，例如 evidence_agent、rule_agent、classification_agent")
    status: str = Field(description="Agent 执行状态，例如 success、failed、skipped")
    confidence: int = Field(ge=0, le=100, description="Agent 对自己判断结果的置信度，范围 0 到 100")
    findings: list[str] = Field(default_factory=list, description="Agent 发现的关键信息，用于 trace 和人工理解")
    output: dict[str, Any] = Field(default_factory=dict, description="Agent 的结构化输出")
    duration_ms: float = Field(ge=0, description="Agent 执行耗时，单位毫秒")


class ApprovalDecision(BaseModel):
    """审批结论：表示系统对一条审批单的最终分流动作。"""

    case_id: str = Field(description="审批结论所属的审批单 ID")
    action: DecisionAction = Field(
        description="最终审批动作：approved、rejected、needs_more_evidence、needs_human_review",
    )
    status: DecisionStatus = Field(description="审批结论状态，例如 completed、pending_review")
    confidence: int = Field(ge=0, le=100, description="最终结论置信度，范围 0 到 100")
    risk_score: int = Field(ge=0, le=100, description="风险分，分数越高表示越不适合自动处理")
    reason: str = Field(description="给审核员看的决策原因")
    suggestion: str = Field(default="", description="给录入员工或审核员看的建议分类或修改建议")
    needs_review: bool = Field(default=False, description="是否需要人工复核")


class ReviewTask(BaseModel):
    """人工复核任务：表示需要审核员介入处理的记录。"""

    task_id: str = Field(description="人工复核任务唯一 ID")
    case_id: str = Field(description="复核任务关联的审批单 ID")
    priority: str = Field(description="复核优先级，例如 low、medium、high")
    reason: str = Field(description="创建复核任务的原因")
    status: str = Field(description="复核任务状态，例如 pending、completed")
    reviewer: str | None = Field(default=None, description="审核员名称，未分配时为空")
    final_action: str | None = Field(
        default=None,
        description="人工最终动作，例如 approved、rejected、unable_to_decide",
    )
    reviewed_at: str | None = Field(default=None, description="???????????????")


class PipelineResult(BaseModel):
    """一批审批单执行后的完整结果。"""

    cases: list[AuditCase] = Field(description="本批次处理的审批单")
    rule_sets: dict[str, CandidateRuleSet] = Field(description="case_id 到候选规则集的映射")
    evidence_packages: dict[str, EvidencePackage] = Field(description="case_id 到证据包的映射")
    decisions: list[ApprovalDecision] = Field(description="本批次审批结论列表")
    review_tasks: list[ReviewTask] = Field(description="本批次需要人工复核的任务列表")
    metrics: dict[str, float | int] = Field(description="本批次审批统计指标")
