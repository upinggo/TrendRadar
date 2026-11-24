# coding=utf-8
"""Single browser-level pytest gate for the generated HTML report flow."""

from pathlib import Path

from trendradar.report.html import prepare_html_for_email, render_html_content


REPORT_DATA = {
    "stats": [
        {
            "word": "AI",
            "count": 1,
            "titles": [
                {
                    "title": "热榜新闻",
                    "source_name": "知乎",
                    "ranks": [8, 4, 1],
                    "rank_timeline": [
                        {"time": "08:00", "rank": 8},
                        {"time": "10:00", "rank": 1},
                    ],
                    "time_display": "08:00 ~ 10:00",
                    "count": 2,
                    "url": "https://zhihu.com/1",
                    "is_new": True,
                }
            ],
        }
    ],
    "new_titles": [],
    "failed_ids": [],
    "total_new_count": 1,
    "search_matched_count": 1,
    "search_new_count": 0,
}


def test_visual_html_report_flow(page, tmp_path):
    """Verify the browser report flow and the sanitized email variant in one gate."""
    html = render_html_content(
        report_data=REPORT_DATA,
        total_titles=3,
        rss_items=[
            {
                "word": "AI",
                "count": 1,
                "titles": [
                    {
                        "title": "RSS测试文章",
                        "source_name": "Hacker News",
                        "time_display": "11-20 09:00",
                        "url": "https://hn.example.com/1",
                        "is_new": False,
                    }
                ],
            }
        ],
        search_items=[
            {
                "word": "AI政策",
                "query": "人工智能 政策",
                "count": 1,
                "titles": [
                    {
                        "title": "联网搜索结果",
                        "url": "https://gov.example.com/ai",
                        "source_name": "政府网",
                        "time_display": "11-24 08:30",
                        "snippet": "生成式人工智能备案要求。",
                        "authority": 4,
                        "score": 0.8,
                        "is_new": False,
                    }
                ],
            }
        ],
        region_order=["hotlist", "rss", "web_search"],
    )
    report_path = tmp_path / "report.html"
    report_path.write_text(html, encoding="utf-8")

    # Narrow viewport makes the initial wide-mode state deterministic.
    page.set_viewport_size({"width": 600, "height": 900})
    page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.url.startswith("http")
        else route.continue_(),
    )
    page.goto(report_path.as_uri())

    assert page.locator(".header-sources-bar").is_visible()
    assert page.locator(".section-nav-bar").is_visible()
    assert page.locator(".trend-badge").count() > 0

    targets = page.locator(
        ".section-nav-btn[data-region-target]"
    ).evaluate_all("els => els.map(e => e.dataset.regionTarget)")
    assert targets[:3] == ["all", "hotlist", "rss"]

    page.locator(".toggle-wide-btn").click()
    assert page.locator("body.wide-mode").count() == 1

    page.locator(".toggle-dark-btn").click()
    assert page.locator("body.dark-mode").count() == 1

    page.locator('.section-nav-btn[data-region-target="rss"]').click()
    assert page.locator("#region-rss").is_visible()

    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    page.screenshot(path=str(artifacts / "report-visual-flow.png"), full_page=True)

    email_html = prepare_html_for_email(html)
    assert "<script" not in email_html.lower()
    assert 'class="email-toc"' in email_html
    assert "section-nav-bar" not in email_html
