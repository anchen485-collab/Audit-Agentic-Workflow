import httpx

from app.infrastructure.website_provider import WebsiteCompanyProvider


def test_website_provider_extracts_homepage_evidence():
    def fake_get(url: str, **kwargs):
        return httpx.Response(
            status_code=200,
            text="""
            <html>
              <head>
                <title>Acme Software</title>
                <meta name="description" content="Acme provides software development services.">
              </head>
              <body>
                <script>ignored()</script>
                <h1>Acme Software</h1>
                <p>We provide software development, platform engineering and system integration.</p>
              </body>
            </html>
            """,
            request=httpx.Request("GET", url),
        )

    provider = WebsiteCompanyProvider(http_get=fake_get)

    evidence = provider.fetch(
        case_id="case_001",
        company_name="Acme Software",
        website_url="example.com",
    )

    assert evidence.case_id == "case_001"
    assert evidence.sources == ["website"]
    assert evidence.quality_score > 0
    assert "software development" in evidence.business_scope.lower()
    assert evidence.snippets


def test_website_provider_returns_empty_evidence_when_url_missing():
    provider = WebsiteCompanyProvider(http_get=lambda url, **kwargs: None)

    evidence = provider.fetch(
        case_id="case_001",
        company_name="Acme Software",
        website_url="",
    )

    assert evidence.quality_score == 0
    assert evidence.snippets == []
    assert evidence.errors


def test_website_provider_collects_business_pages_with_alias_names():
    requested_urls: list[str] = []
    pages = {
        "https://example.com": """
            <html>
              <head><title>南宁智慧医疗有限公司</title></head>
              <body>
                <h1>南宁智慧医疗有限公司</h1>
                <a href="/hospital-profile">医院概况</a>
                <a href="/clinical-service">诊疗服务</a>
                <a href="/solution">智慧医院解决方案</a>
                <a href="/business-area">业务领域</a>
                <a href="/contact-us">联系我们</a>
                <a href="/news">新闻动态</a>
              </body>
            </html>
        """,
        "https://example.com/hospital-profile": """
            <html><body><main>公司专注医疗信息化平台建设，提供医院运营系统研发服务。</main></body></html>
        """,
        "https://example.com/clinical-service": """
            <html><body><main>产品服务包括专科诊疗平台、远程问诊系统和医院数据集成。</main></body></html>
        """,
        "https://example.com/solution": """
            <html><body><main>解决方案覆盖智慧医院、医保控费和临床辅助决策。</main></body></html>
        """,
        "https://example.com/business-area": """
            <html><body><main>业务领域包含医疗软件、数据平台和系统集成服务。</main></body></html>
        """,
        "https://example.com/contact-us": """
            <html><body><main>联系我们页面展示医院软件服务团队和客户支持能力。</main></body></html>
        """,
    }

    def fake_get(url: str, **kwargs):
        requested_urls.append(url)
        return httpx.Response(
            status_code=200,
            text=pages[url],
            request=httpx.Request("GET", url),
        )

    provider = WebsiteCompanyProvider(http_get=fake_get)

    evidence = provider.fetch(
        case_id="case_002",
        company_name="南宁智慧医疗有限公司",
        website_url="example.com",
    )

    assert requested_urls == [
        "https://example.com",
        "https://example.com/hospital-profile",
        "https://example.com/clinical-service",
        "https://example.com/solution",
        "https://example.com/business-area",
        "https://example.com/contact-us",
    ]
    assert "新闻动态" not in evidence.business_scope
    assert "医疗信息化平台建设" in evidence.business_scope
    assert "智慧医院" in evidence.business_scope
    assert "医疗软件" in evidence.business_scope
    assert len(evidence.snippets) >= 3


def test_website_provider_ignores_footer_noise():
    def fake_get(url: str, **kwargs):
        return httpx.Response(
            status_code=200,
            text="""
            <html>
              <head><title>东方专科医院</title></head>
              <body>
                <main>
                  <h1>东方专科医院</h1>
                  <p>医院提供骨科诊疗服务、康复治疗服务和专科医疗护理。</p>
                </main>
                <footer>
                  Copyright © 2023 东方专科医院 版权所有
                  ICP备案/许可证号：桂ICP备18005012号
                  电话：0515-85473888 地址：江苏省东台市海丰社区
                </footer>
              </body>
            </html>
            """,
            request=httpx.Request("GET", url),
        )

    provider = WebsiteCompanyProvider(http_get=fake_get)

    evidence = provider.fetch(
        case_id="case_003",
        company_name="东方专科医院",
        website_url="example.com",
    )

    assert "骨科诊疗服务" in evidence.business_scope
    assert "ICP" not in evidence.business_scope
    assert "Copyright" not in evidence.business_scope
    assert "0515-85473888" not in evidence.business_scope


def test_website_provider_uses_browser_like_headers_for_firewall_sites():
    """部分官网防火墙会拦截非浏览器请求，爬虫应该发送浏览器形态请求头。"""
    observed_headers = {}

    def fake_get(url: str, **kwargs):
        observed_headers.update(kwargs.get("headers", {}))
        if "Mozilla/5.0" not in observed_headers.get("User-Agent", ""):
            return httpx.Response(
                status_code=403,
                text="<title>宝塔网站防火墙免费版</title>",
                request=httpx.Request("GET", url),
            )

        return httpx.Response(
            status_code=200,
            text="""
            <html>
              <head><title>西安唯拓尔农业科技有限公司</title></head>
              <body><main>公司专注控释肥料、缓释肥料和农业技术服务。</main></body>
            </html>
            """,
            request=httpx.Request("GET", url),
        )

    provider = WebsiteCompanyProvider(http_get=fake_get)

    evidence = provider.fetch(
        case_id="case_firewall",
        company_name="西安唯拓尔农业科技有限公司",
        website_url="https://www.virtor-agr.com/",
    )

    assert evidence.quality_score > 0
    assert "控释肥料" in evidence.business_scope
    assert observed_headers["Accept-Language"].startswith("zh-CN")


def test_website_provider_retries_homepage_url_variants_when_forbidden():
    """首页被 403 拦截时，应该尝试同域名的 www/非 www 和 http/https 变体。"""
    requested_urls: list[str] = []

    def fake_get(url: str, **kwargs):
        requested_urls.append(url)
        if url == "https://www.blocked.example-site.com/":
            return httpx.Response(
                status_code=403,
                text="forbidden",
                request=httpx.Request("GET", url),
            )

        if url == "https://blocked.example-site.com/":
            return httpx.Response(
                status_code=200,
                text="""
                <html>
                  <head><title>可访问农业公司</title></head>
                  <body><main>公司提供农产品种植、加工和销售服务。</main></body>
                </html>
                """,
                request=httpx.Request("GET", url),
            )

        return httpx.Response(
            status_code=404,
            text="not found",
            request=httpx.Request("GET", url),
        )

    provider = WebsiteCompanyProvider(http_get=fake_get)

    evidence = provider.fetch(
        case_id="case_retry",
        company_name="可访问农业公司",
        website_url="https://www.blocked.example-site.com/",
    )

    assert requested_urls[:2] == [
        "https://www.blocked.example-site.com/",
        "https://blocked.example-site.com/",
    ]
    assert evidence.quality_score > 0
    assert "农产品种植" in evidence.business_scope
