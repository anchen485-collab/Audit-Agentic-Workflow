import re
from collections.abc import Callable
from html.parser import HTMLParser
from time import perf_counter
from urllib.parse import urljoin, urlparse

import httpx

from app.domain.models import EvidencePackage, EvidenceSnippet
from app.observability.logging import get_audit_logger

logger = get_audit_logger("infrastructure.website_provider")

TARGET_PAGE_ALIASES = [
    [
        "关于我们",
        "公司简介",
        "企业简介",
        "医院简介",
        "医院概况",
        "公司概况",
        "企业概况",
        "机构简介",
        "集团简介",
        "about",
        "profile",
        "overview",
        "introduction",
    ],
    [
        "产品服务",
        "产品中心",
        "服务项目",
        "服务范围",
        "诊疗服务",
        "医疗服务",
        "科室介绍",
        "产品",
        "服务",
        "product",
        "service",
    ],
    [
        "解决方案",
        "方案中心",
        "行业方案",
        "智慧方案",
        "solution",
        "solutions",
    ],
    [
        "业务范围",
        "业务领域",
        "主营业务",
        "经营范围",
        "业务介绍",
        "业务板块",
        "业务方向",
        "business",
        "scope",
        "field",
    ],
    [
        "联系我们",
        "联系方式",
        "联系",
        "contact",
        "contact-us",
    ],
]

FOOTER_NOISE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"copyright",
        r"版权所有",
        r"备案",
        r"许可证",
        r"公网安备",
        r"营业执照",
        r"all rights reserved",
        r"\bICP\b",
        r"\d{3,4}-\d{6,8}",
    ]
]
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class _WebsiteTextParser(HTMLParser):
    """从官网 HTML 中抽取 title、meta description 和正文文本。"""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._in_title = False
        self._current_link: str | None = None
        self._current_link_text_parts: list[str] = []
        self._ignored_tag_depth = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        attr_map = {name.lower(): value for name, value in attrs if value}

        if tag == "a":
            self._current_link = attr_map.get("href")
            self._current_link_text_parts = []

        if tag in {"script", "style", "noscript", "svg", "footer"}:
            self._ignored_tag_depth += 1
            return

        if tag == "title":
            self._in_title = True
            return

        if tag == "meta":
            meta_name = attr_map.get("name", "").lower()
            meta_property = attr_map.get("property", "").lower()

            if meta_name == "description" or meta_property == "og:description":
                self.meta_description = attr_map.get("content", "")

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if tag == "a" and self._current_link:
            self.links.append((self._current_link, _clean_text(" ".join(self._current_link_text_parts))))
            self._current_link = None
            self._current_link_text_parts = []

        if tag in {"script", "style", "noscript", "svg", "footer"} and self._ignored_tag_depth:
            self._ignored_tag_depth -= 1

        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str):
        text = _clean_text(data)

        if not text or self._ignored_tag_depth:
            return

        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return

        if self._current_link:
            self._current_link_text_parts.append(text)
            return

        self.text_parts.append(text)


class WebsiteCompanyProvider:
    """企业官网证据 provider，采集官网首页和高价值业务子页面。"""

    def __init__(
        self,
        timeout_seconds: float = 8,
        user_agent: str = DEFAULT_BROWSER_USER_AGENT,
        http_get: Callable[..., httpx.Response] = httpx.get,
        max_child_pages: int = 5,
    ):
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.http_get = http_get
        self.max_child_pages = max_child_pages

    def fetch(
        self,
        case_id: str,
        company_name: str,
        website_url: str = "",
    ) -> EvidencePackage:
        """访问企业官网首页并生成 EvidencePackage。"""
        start_time = perf_counter()
        if not website_url.strip():
            logger.warning(
                "官网爬虫跳过: case_id=%s company=%s duration_ms=%.3f reason=缺少官网 URL",
                case_id,
                company_name,
                _elapsed_ms(start_time),
            )
            return self._empty_package(case_id, company_name, "缺少企业官网 URL。")

        normalized_url = self._normalize_url(website_url)
        logger.info("官网爬虫开始: case_id=%s company=%s url=%s", case_id, company_name, normalized_url)

        try:
            homepage_url, homepage_parser = self._fetch_homepage(normalized_url)
        except Exception as error:
            logger.warning(
                "官网爬虫失败: case_id=%s company=%s url=%s duration_ms=%.3f reason=%s",
                case_id,
                company_name,
                normalized_url,
                _elapsed_ms(start_time),
                error,
            )
            return self._empty_package(case_id, company_name, f"官网访问失败：{error}")

        page_parsers = [(homepage_url, homepage_parser)]
        child_urls = self._select_target_page_urls(homepage_parser, homepage_url)
        for child_url in child_urls:
            try:
                page_parsers.append((child_url, self._fetch_page(child_url)))
            except Exception as error:
                logger.warning(
                    "官网子页面爬取失败: case_id=%s company=%s url=%s duration_ms=%.3f reason=%s",
                    case_id,
                    company_name,
                    child_url,
                    _elapsed_ms(start_time),
                    error,
                )

        business_scope = self._build_combined_business_scope(page_parsers)
        snippets = self._build_snippets(page_parsers)
        quality_score = self._calculate_quality_score(page_parsers, business_scope, snippets)
        logger.info(
            "官网爬虫完成: case_id=%s company=%s duration_ms=%.3f page_count=%s "
            "quality_score=%s snippet_count=%s text_length=%s",
            case_id,
            company_name,
            _elapsed_ms(start_time),
            len(page_parsers),
            quality_score,
            len(snippets),
            len(business_scope),
        )

        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=["website"],
            business_scope=business_scope,
            snippets=snippets,
            quality_score=quality_score,
            errors=[] if snippets else ["官网页面未抽取到有效业务片段。"],
        )

    def _fetch_homepage(self, url: str) -> tuple[str, _WebsiteTextParser]:
        """请求首页；如果被防火墙或协议差异拦截，尝试常见 URL 变体。"""
        errors = []
        for candidate_url in self._homepage_url_candidates(url):
            try:
                return candidate_url, self._fetch_page(candidate_url)
            except Exception as error:
                errors.append(f"{candidate_url}: {error}")
                logger.info("官网首页候选访问失败: url=%s reason=%s", candidate_url, error)

        raise ValueError("；".join(errors))

    def _fetch_page(self, url: str) -> _WebsiteTextParser:
        """请求单个官网页面，并解析出文本和链接。"""
        response = self.http_get(
            url,
            headers=self._request_headers(),
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()

        parser = _WebsiteTextParser()
        parser.feed(response.text)
        return parser

    def _request_headers(self) -> dict[str, str]:
        """构造接近正常浏览器访问的请求头，降低被基础防火墙误拦截的概率。"""
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
        }

    def _normalize_url(self, website_url: str) -> str:
        """补全 URL 协议。"""
        website_url = website_url.strip()

        if website_url.startswith(("http://", "https://")):
            return website_url

        return f"https://{website_url}"

    def _homepage_url_candidates(self, url: str) -> list[str]:
        """生成首页候选 URL，兼容 www/非 www 和 http/https 差异。"""
        parsed_url = urlparse(url)
        netloc = parsed_url.netloc
        if not netloc:
            return [url]

        path = parsed_url.path
        schemes = [parsed_url.scheme or "https"]
        if "https" not in schemes:
            schemes.append("https")
        if "http" not in schemes:
            schemes.append("http")

        hosts = [netloc]
        if netloc.startswith("www."):
            hosts.append(netloc.removeprefix("www."))
        else:
            hosts.append(f"www.{netloc}")

        candidates = []
        for scheme in schemes:
            for host in hosts:
                candidate = parsed_url._replace(scheme=scheme, netloc=host, path=path, fragment="").geturl()
                if candidate not in candidates:
                    candidates.append(candidate)

        return candidates

    def _select_target_page_urls(self, parser: _WebsiteTextParser, base_url: str) -> list[str]:
        """从首页链接中筛选关于、产品服务、解决方案、业务范围、联系等高价值页面。"""
        selected_by_group: dict[int, str] = {}
        base_netloc = urlparse(base_url).netloc

        for href, link_text in parser.links:
            absolute_url = self._normalize_child_url(base_url, href)
            if not absolute_url:
                continue

            parsed_url = urlparse(absolute_url)
            if parsed_url.netloc and parsed_url.netloc != base_netloc:
                continue

            link_signal = f"{link_text} {parsed_url.path}".lower()
            group_index = self._match_target_group(link_signal)
            if group_index is None or group_index in selected_by_group:
                continue

            selected_by_group[group_index] = absolute_url
            if len(selected_by_group) >= self.max_child_pages:
                break

        return list(selected_by_group.values())

    def _normalize_child_url(self, base_url: str, href: str) -> str:
        """把页面链接转成绝对地址，过滤锚点、电话、邮箱和脚本链接。"""
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return ""

        absolute_url = urljoin(base_url, href)
        parsed_url = urlparse(absolute_url)
        if parsed_url.scheme not in {"http", "https"}:
            return ""

        return parsed_url._replace(fragment="").geturl()

    def _match_target_group(self, link_signal: str) -> int | None:
        """根据链接文字和路径判断它属于哪类目标页面。"""
        for group_index, aliases in enumerate(TARGET_PAGE_ALIASES):
            if any(alias.lower() in link_signal for alias in aliases):
                return group_index

        return None

    def _build_combined_business_scope(self, page_parsers: list[tuple[str, _WebsiteTextParser]]) -> str:
        """合并首页和目标子页面文本，形成给 Agent 使用的业务描述。"""
        page_scopes = [self._build_business_scope(parser) for _, parser in page_parsers]
        return _clean_text(" ".join(scope for scope in page_scopes if scope))

    def _build_business_scope(self, parser: _WebsiteTextParser) -> str:
        """汇总官网 title、description 和正文片段。"""
        page_text = " ".join(_filter_noise_text(text) for text in parser.text_parts)
        return _clean_text(" ".join([parser.title, parser.meta_description, page_text]))

    def _build_snippets(self, page_parsers: list[tuple[str, _WebsiteTextParser]]) -> list[EvidenceSnippet]:
        """按页面生成证据片段，保留片段来自哪个 URL。"""
        snippets: list[EvidenceSnippet] = []
        for url, parser in page_parsers:
            business_scope = self._build_business_scope(parser)
            snippets.extend(
                EvidenceSnippet(source="website", text=text, url=url)
                for text in self._select_snippets(business_scope)
            )

        return snippets[:8]

    def _select_snippets(self, business_scope: str) -> list[str]:
        """选择最适合作为证据的业务片段。"""
        if not business_scope:
            return []

        sentences = re.split(r"(?<=[。.!?])\s+|\n+", business_scope)
        business_keywords = [
            "业务",
            "服务",
            "产品",
            "研发",
            "生产",
            "销售",
            "解决方案",
            "平台",
            "系统",
            "software",
            "service",
            "platform",
            "development",
            "integration",
        ]
        matched = [
            sentence.strip()
            for sentence in sentences
            if sentence.strip() and any(keyword.lower() in sentence.lower() for keyword in business_keywords)
        ]

        if matched:
            return matched[:3]

        return [business_scope[:300]]

    def _calculate_quality_score(
        self,
        page_parsers: list[tuple[str, _WebsiteTextParser]],
        business_scope: str,
        snippets: list[EvidenceSnippet],
    ) -> int:
        """根据抽取内容粗略估算证据质量分。"""
        score = 0
        homepage_parser = page_parsers[0][1]

        if homepage_parser.title:
            score += 15

        if any(parser.meta_description for _, parser in page_parsers):
            score += 25

        if business_scope:
            score += 25

        if snippets:
            score += 30

        if len(business_scope) >= 120:
            score += 5

        if len(page_parsers) > 1:
            score += min((len(page_parsers) - 1) * 5, 20)

        return min(score, 100)

    def _empty_package(self, case_id: str, company_name: str, error: str) -> EvidencePackage:
        """生成证据缺失时的兜底 EvidencePackage。"""
        return EvidencePackage(
            case_id=case_id,
            company_name=company_name,
            sources=[],
            business_scope="",
            snippets=[],
            quality_score=0,
            errors=[error],
        )


def _clean_text(text: str) -> str:
    """压缩 HTML 文本中的多余空白。"""
    return re.sub(r"\s+", " ", text).strip()


def _filter_noise_text(text: str) -> str:
    """过滤官网底部常见备案、版权、电话地址等噪声文本。"""
    text = _clean_text(text)
    if not text:
        return ""

    if any(pattern.search(text) for pattern in FOOTER_NOISE_PATTERNS):
        return ""

    return text


def _elapsed_ms(start_time: float) -> float:
    """计算从 start_time 到当前时间的毫秒耗时。"""
    return round((perf_counter() - start_time) * 1000, 3)
