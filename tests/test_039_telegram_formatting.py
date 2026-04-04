from core.telegram_formatting import format_source_links_markdown, render_telegram_html


def test_format_source_links_markdown_uses_short_labels_and_full_urls():
    block = format_source_links_markdown(
        [
            {
                "title": "OpenAI update",
                "url": "https://openai.com/index/introducing-new-model/",
            },
            {
                "title": "NASA mission",
                "url": "https://www.nasa.gov/missions/artemis-ii/",
            },
        ]
    )

    assert "- [openai.com](https://openai.com/index/introducing-new-model/)" in block
    assert "- [nasa.gov](https://www.nasa.gov/missions/artemis-ii/)" in block


def test_render_telegram_html_converts_basic_markdown_and_links():
    rendered = render_telegram_html(
        "*жирно* _курсив_ `код`\n\n"
        "Джерела:\n"
        "- [nasa.gov](https://www.nasa.gov/missions/artemis-ii/)"
    )

    assert "<b>жирно</b>" in rendered
    assert "<i>курсив</i>" in rendered
    assert "<code>код</code>" in rendered
    assert (
        '<a href="https://www.nasa.gov/missions/artemis-ii/">nasa.gov</a>' in rendered
    )


def test_render_telegram_html_converts_code_fences_to_pre():
    rendered = render_telegram_html("```python\nprint('hi')\n```")

    assert "<pre><code>print(&#x27;hi&#x27;)</code></pre>" == rendered


def test_render_telegram_html_supports_nested_bracket_link_labels():
    rendered = render_telegram_html(
        "Перевірка [[1]](https://www.nasa.gov/missions/artemis-ii/)"
    )

    assert '<a href="https://www.nasa.gov/missions/artemis-ii/">[1]</a>' in rendered
