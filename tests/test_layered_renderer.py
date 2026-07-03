from __future__ import annotations

from llm_relay_desk.desktop.layered_renderer import compose_subtitle_image, wrap_text, load_font


def base_config() -> dict[str, object]:
    return {
        "font_size": 28,
        "text_opacity": 1.0,
        "background_opacity": 0.0,
        "background_color": "#101318",
        "text_color": "#ffffff",
        "muted_color": "#aeb6c2",
        "border_color": "#343a46",
        "error_color": "#ff8f9b",
        "text_shadow": True,
        "shadow_color": "#000000",
        "shadow_offset": 2,
    }


def test_zero_background_keeps_antialiased_text_pixels() -> None:
    image = compose_subtitle_image(
        width=720,
        height=180,
        status="模型 · 正在生成",
        body="透明背景字幕应保持平滑边缘",
        body_kind=None,
        positioning=False,
        show_close=False,
        config=base_config(),
    )
    alpha = image.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0
    minimum, maximum = alpha.getextrema()
    assert minimum == 0
    assert maximum > 200
    assert any(0 < value < 255 for value in alpha.get_flattened_data())


def test_text_opacity_is_independent_from_background() -> None:
    config = base_config()
    config["text_opacity"] = 0.4
    image = compose_subtitle_image(
        width=720,
        height=180,
        status="模型 · 正在生成",
        body="独立文字透明度",
        body_kind=None,
        positioning=False,
        show_close=False,
        config=config,
    )
    assert image.getchannel("A").getextrema()[1] <= 110


def test_background_opacity_does_not_reduce_text_alpha() -> None:
    config = base_config()
    config["background_opacity"] = 0.25
    image = compose_subtitle_image(
        width=720,
        height=180,
        status="模型 · 正在生成",
        body="文字仍保持清晰",
        body_kind=None,
        positioning=False,
        show_close=True,
        config=config,
    )
    alpha = image.getchannel("A")
    assert 55 <= alpha.getpixel((30, 30)) <= 80
    assert alpha.getextrema()[1] > 220


def test_wrap_text_handles_chinese_without_spaces() -> None:
    font = load_font(20)
    lines = wrap_text("这是没有空格的中文长句，用于测试按字形宽度自动换行。", font, 100)
    assert len(lines) > 1
    assert "".join(lines) == "这是没有空格的中文长句，用于测试按字形宽度自动换行。"
