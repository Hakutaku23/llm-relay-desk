from __future__ import annotations

from llm_relay_desk.desktop.layered_renderer import compose_subtitle_image, wrap_text, load_font


def base_config() -> dict[str, object]:
    return {
        "font_size": 28,
        "font_family": "Microsoft YaHei UI",
        "text_align": "left",
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


def _alpha_bbox(image):
    return image.getchannel("A").getbbox()


def test_transparent_text_defaults_to_left_alignment() -> None:
    config = base_config()
    config["text_align"] = "left"
    image = compose_subtitle_image(
        width=720,
        height=180,
        status="模型 · 正在生成",
        body="左对齐透明字幕",
        body_kind=None,
        positioning=False,
        show_close=False,
        config=config,
    )
    bbox = _alpha_bbox(image)
    assert bbox is not None
    assert bbox[0] < 80


def test_transparent_text_alignment_can_be_centered_or_right() -> None:
    left = base_config()
    left["text_align"] = "left"
    center = {**left, "text_align": "center"}
    right = {**left, "text_align": "right"}
    kwargs = dict(
        width=720,
        height=180,
        status="模型 · 正在生成",
        body="对齐测试",
        body_kind=None,
        positioning=False,
        show_close=False,
    )
    left_box = _alpha_bbox(compose_subtitle_image(config=left, **kwargs))
    center_box = _alpha_bbox(compose_subtitle_image(config=center, **kwargs))
    right_box = _alpha_bbox(compose_subtitle_image(config=right, **kwargs))
    assert left_box and center_box and right_box
    assert left_box[0] < center_box[0] < right_box[0]


def test_unknown_font_family_falls_back_without_error() -> None:
    config = base_config()
    config["font_family"] = "Definitely Missing Font Family"
    image = compose_subtitle_image(
        width=640,
        height=160,
        status="模型",
        body="字体回退测试",
        body_kind=None,
        positioning=False,
        show_close=False,
        config=config,
    )
    assert image.getchannel("A").getextrema()[1] > 0


def test_missing_cjk_font_uses_cjk_fallback() -> None:
    fallback = base_config()
    fallback["font_family"] = "Microsoft YaHei UI"
    missing = {**fallback, "font_family": "Definitely Missing Font Family"}
    kwargs = dict(
        width=640,
        height=160,
        status="模型",
        body="中文字体回退",
        body_kind=None,
        positioning=False,
        show_close=False,
    )
    fallback_image = compose_subtitle_image(config=fallback, **kwargs)
    missing_image = compose_subtitle_image(config=missing, **kwargs)
    assert missing_image.tobytes() == fallback_image.tobytes()
