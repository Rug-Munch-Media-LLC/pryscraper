"""Tests for shadow DOM flattening."""

from shadow_dom import ShadowDOMProcessor, flatten_shadow_dom, has_shadow_dom


def test_has_shadow_dom_detected() -> None:
    html = '<html><body><template shadowroot="open"><p>Shadow content</p></template></body></html>'
    assert has_shadow_dom(html) is True


def test_has_shadow_dom_not_detected() -> None:
    html = "<html><body><p>Regular content</p></body></html>"
    assert has_shadow_dom(html) is False


def test_flatten_shadow_dom_open() -> None:
    html = '<div><template shadowroot="open"><p>Shadow content</p></template></div>'
    result = flatten_shadow_dom(html)
    assert "template" not in result
    assert "Shadow content" in result


def test_flatten_shadow_dom_closed() -> None:
    html = '<div><template shadowroot="closed"><p>Hidden</p></template></div>'
    result = flatten_shadow_dom(html)
    assert "template" not in result
    assert "Hidden" in result


def test_flatten_shadow_dom_declarative_mode() -> None:
    html = '<div><template shadowrootmode="open"><span>Declarative</span></template></div>'
    result = flatten_shadow_dom(html)
    assert "template" not in result
    assert "Declarative" in result


def test_processor_regular_html() -> None:
    processor = ShadowDOMProcessor()
    html = "<html><body><p>Hello</p></body></html>"
    result = processor.process(html)
    assert result == html


def test_processor_with_shadow() -> None:
    processor = ShadowDOMProcessor()
    html = '<html><body><template shadowroot="open"><p>In shadow</p></template></body></html>'
    result = processor.process(html)
    assert "In shadow" in result
    assert "template" not in result


def test_has_shadow_dom_attach_shadow() -> None:
    html = "<script>element.attachShadow({mode: 'open'})</script>"
    assert has_shadow_dom(html) is True


def test_has_shadow_dom_shadowroot_string() -> None:
    html = "<script>#shadow-root (open)</script>"
    assert has_shadow_dom(html) is True
