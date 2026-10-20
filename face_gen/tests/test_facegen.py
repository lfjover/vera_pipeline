import json
from types import SimpleNamespace

import pytest
from PIL import Image

from facegen import cli
from facegen import masks
from facegen.grid import contact_sheet, grid_recipes
from facegen.painter import Painter, composite, load_image
from facegen.recipe import MODEL_ALIASES, Recipe, expand_options, read_text_arg, resolve_model


class FakePipe:
    """Stands in for the diffusers pipeline: records calls, returns the input image tinted."""

    def __init__(self):
        self.calls = []
        self.tokenizer = lambda text: {"input_ids": text.split()}

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(images=[Image.new("RGB", kwargs["image"].size, "purple")])


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "face.jpg"
    Image.new("RGB", (1000, 1500), "green").save(path)
    return path


@pytest.fixture
def fake(monkeypatch):
    pipe = FakePipe()
    painters = []

    def build(model, task="img2img"):
        painters.append(Painter(model, device="cpu", pipeline=pipe, task=task))
        return painters[-1]

    monkeypatch.setattr(cli, "build_painter", build)
    return SimpleNamespace(pipe=pipe, painters=painters)


def test_load_image_shrinks_to_size_and_multiples_of_8(photo):
    image = load_image(photo, size=768)
    assert image.size == (512, 768)


def test_load_image_enlarges_small_photos(tmp_path):
    path = tmp_path / "small.png"
    Image.new("L", (480, 638)).save(path)  # small grayscale screenshot
    image = load_image(path, size=1024)
    assert image.mode == "RGB"
    assert image.size == (768, 1024)


def test_recipe_size_defaults_to_the_model_native_size():
    assert Recipe(prompt="p", input="x").size == 768
    assert Recipe(prompt="p", input="x", model=resolve_model("sdxl")).size == 1024
    assert Recipe(prompt="p", input="x", model=resolve_model("sdxl"), size=896).size == 896


def test_recipes_saved_with_max_side_still_load(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"prompt": "p", "input": "x", "seed": 1, "max_side": 640}))
    assert Recipe.load(path).size == 640


def test_recipe_round_trip_ignores_unknown_keys(tmp_path):
    recipe = Recipe(prompt="goddess", input="x.jpg", seed=42)
    path = tmp_path / "r.json"
    recipe.save(path)
    data = json.loads(path.read_text())
    path.write_text(json.dumps({**data, "added_later": True}))
    assert Recipe.load(path) == recipe


def test_read_text_arg_reads_files(tmp_path):
    (tmp_path / "p.txt").write_text("  mother earth \n")
    assert read_text_arg(f"@{tmp_path / 'p.txt'}") == "mother earth"
    assert read_text_arg("plain") == "plain"
    assert read_text_arg(None) is None


def test_paint_passes_settings_and_seed(photo):
    pipe = FakePipe()
    painter = Painter(pipeline=pipe)
    painter.paint(Recipe(prompt="p", input=str(photo), negative="", strength=0.7, guidance=6.5, steps=30, seed=7))
    call = pipe.calls[0]
    assert (call["strength"], call["guidance_scale"], call["num_inference_steps"]) == (0.7, 6.5, 30)
    assert call["negative_prompt"] is None
    assert call["generator"].initial_seed() == 7


def test_paint_refuses_recipe_for_another_model(photo):
    painter = Painter(pipeline=FakePipe())
    with pytest.raises(ValueError, match="other/model"):
        painter.paint(Recipe(prompt="p", input=str(photo), model="other/model"))


def test_prompt_warnings_flag_prompts_over_77_tokens():
    painter = Painter(pipeline=FakePipe())
    recipe = Recipe(prompt="short", input="x", negative=" ".join(["ugly"] * 80))
    assert painter.prompt_warnings(recipe) == ["negative is 80 tokens; only the first 77 are used"]


def test_generate_saves_png_and_recipe_per_seed(photo, tmp_path, fake):
    out = tmp_path / "out"
    code = cli.main(["generate", "-i", str(photo), "-p", "mother earth", "--seed", "100", "--count", "2", "-o", str(out)])
    assert code == 0
    pngs = sorted(out.glob("*.png"))
    assert [p.name.split("_")[-1] for p in pngs] == ["s100.png", "s101.png"]
    assert Recipe.load(pngs[1].with_suffix(".json")).seed == 101
    assert len(fake.painters) == 1 and len(fake.pipe.calls) == 2  # one model load for all images


def test_grid_saves_cells_and_contact_sheet(photo, tmp_path, fake):
    out = tmp_path / "out"
    code = cli.main(["grid", "-i", str(photo), "-p", "goddess", "--strengths", "0.5,0.6",
                     "--guidances", "5,6,7", "--steps", "10", "-o", str(out)])
    assert code == 0
    (grid_dir,) = out.iterdir()
    assert len(list(grid_dir.glob("r*c*_s*.png"))) == 6
    assert len(list(grid_dir.glob("r*c*_s*.json"))) == 6
    assert (grid_dir / "contact_sheet.png").is_file()
    assert [c["strength"] for c in fake.pipe.calls] == [0.5] * 3 + [0.6] * 3
    assert [c["guidance_scale"] for c in fake.pipe.calls] == [5, 6, 7] * 2


def test_grid_seeds_differ_unless_same_seed():
    base = Recipe(prompt="p", input="x", seed=1)
    seeds = {r.seed for row in grid_recipes(base, [0.5, 0.6], [5, 6]) for r in row}
    assert len(seeds) > 1
    assert {r.seed for row in grid_recipes(base, [0.5, 0.6], [5, 6], same_seed=True) for r in row} == {1}


def test_contact_sheet_size():
    images = [[Image.new("RGB", (512, 768))] * 3] * 2
    sheet = contact_sheet(images, [["label"] * 3] * 2, thumb=100)
    assert sheet.size == (300, 2 * (150 + 44))


def test_rerun_keeps_recipe_and_applies_overrides(photo, tmp_path, fake):
    saved = tmp_path / "saved.json"
    Recipe(prompt="goddess", input=str(photo), strength=0.6, guidance=6, steps=50, seed=9).save(saved)
    out = tmp_path / "out"
    assert cli.main(["rerun", str(saved), "--strength", "0.7", "-o", str(out)]) == 0
    (new_json,) = out.glob("*.json")
    rerun = Recipe.load(new_json)
    assert (rerun.seed, rerun.strength, rerun.guidance, rerun.steps) == (9, 0.7, 6, 50)


def test_rerun_with_missing_photo_is_an_error(tmp_path, fake, capsys):
    saved = tmp_path / "saved.json"
    Recipe(prompt="p", input=str(tmp_path / "gone.jpg")).save(saved)
    assert cli.main(["rerun", str(saved)]) == 2
    assert "not found" in capsys.readouterr().err
    assert fake.pipe.calls == []


def test_bad_strength_list_is_an_error(photo, fake, capsys):
    assert cli.main(["grid", "-i", str(photo), "-p", "p", "--strengths", "0.5,abc"]) == 2
    assert "comma-separated" in capsys.readouterr().err



def test_sdxl_shortcut_resolves_and_uses_1024(photo, tmp_path, fake):
    out = tmp_path / "out"
    assert cli.main(["generate", "-i", str(photo), "-p", "p", "--model", "sdxl", "-o", str(out)]) == 0
    (saved,) = out.glob("*.json")
    recipe = Recipe.load(saved)
    assert (recipe.model, recipe.size) == (MODEL_ALIASES["sdxl"], 1024)
    assert fake.painters[0].model == MODEL_ALIASES["sdxl"]
    assert max(fake.pipe.calls[0]["image"].size) == 1024


# ------------------------------------------------------------------ variations
def left_half_mask(image):
    mask = Image.new("L", image.size, 0)
    mask.paste(255, (0, 0, image.width // 2, image.height))
    return mask


@pytest.fixture
def fake_mask(monkeypatch):
    monkeypatch.setattr(masks, "face_hair_mask", left_half_mask)


def test_expand_options_is_seeded_and_ignores_plain_braces():
    template = "a {red|black|blonde} {bob|braids} {plain}"
    assert expand_options(template, 5) == expand_options(template, 5)
    assert len({expand_options(template, seed) for seed in range(40)}) > 1
    assert expand_options(template, 5).endswith("{plain}")
    assert "|" not in expand_options(template, 5)


def test_with_seed_picks_options_but_keeps_the_template_untouched():
    base = Recipe(prompt="{x|y} hair", input="i", negative="{ugly|blurry}")
    picked = base.with_seed(3)
    assert picked.prompt in {"x hair", "y hair"} and picked.negative in {"ugly", "blurry"}
    assert base.prompt == "{x|y} hair"


def test_composite_keeps_background_pixels_exactly():
    original = Image.new("RGB", (200, 100), (10, 120, 200))
    painted = Image.new("RGB", (200, 100), (250, 0, 0))
    out = composite(original, painted, left_half_mask(original))
    assert out.getpixel((10, 50)) == (250, 0, 0)        # inside the mask: repainted
    assert out.getpixel((190, 50)) == (10, 120, 200)    # well outside: untouched


def test_composite_keeps_black_and_white_photos_black_and_white():
    original = Image.new("RGB", (64, 64), (128, 128, 128))
    out = composite(original, Image.new("RGB", (64, 64), (250, 0, 0)), Image.new("L", (64, 64), 255))
    r, g, b = out.getpixel((32, 32))
    assert r == g == b


def test_vary_inpaints_with_the_mask_and_saves_everything(photo, tmp_path, fake, fake_mask):
    out = tmp_path / "out"
    code = cli.main(["vary", "-i", str(photo), "-p", "{red|black} hair", "--count", "3", "--seed", "10",
                     "--grow", "0", "-o", str(out)])
    assert code == 0
    (vary_dir,) = out.iterdir()
    assert sorted(p.name for p in vary_dir.glob("v*.png")) == ["v1_s10.png", "v2_s11.png", "v3_s12.png"]
    assert (vary_dir / "mask.png").is_file() and (vary_dir / "contact_sheet.png").is_file()
    recipe = Recipe.load(vary_dir / "v1_s10.json")
    assert (recipe.task, recipe.mask, recipe.model) == ("inpaint", "face_hair", MODEL_ALIASES["sd15-inpaint"])
    assert recipe.prompt in {"red hair", "black hair"}
    assert fake.painters[0].task == "inpaint" and len(fake.painters) == 1
    call = fake.pipe.calls[0]
    assert call["mask_image"].size == call["image"].size
    assert (call["width"], call["height"]) == call["image"].size
    result = Image.open(vary_dir / "v1_s10.png")
    photo_pixel = load_image(photo, recipe.size).getpixel((result.width - 5, 5))
    assert result.getpixel((result.width - 5, 5)) == photo_pixel  # background untouched


def test_vary_sdxl_uses_the_sdxl_inpainting_model(photo, tmp_path, fake, fake_mask):
    assert cli.main(["vary", "-i", str(photo), "-p", "p", "--count", "1", "--model", "sdxl", "-o", str(tmp_path)]) == 0
    assert fake.painters[0].model == MODEL_ALIASES["sdxl-inpaint"]


def test_vary_with_an_empty_mask_is_an_error(photo, tmp_path, fake, monkeypatch, capsys):
    monkeypatch.setattr(masks, "face_hair_mask", lambda image: Image.new("L", image.size, 0))
    assert cli.main(["vary", "-i", str(photo), "-p", "p", "-o", str(tmp_path)]) == 2
    assert "no face or hair" in capsys.readouterr().err
    assert fake.pipe.calls == []


def test_rerun_of_a_variation_rebuilds_its_mask(photo, tmp_path, fake, fake_mask):
    saved = tmp_path / "v.json"
    Recipe(prompt="p", input=str(photo), model=MODEL_ALIASES["sd15-inpaint"], task="inpaint", mask="face_hair").save(saved)
    assert cli.main(["rerun", str(saved), "-o", str(tmp_path / "out")]) == 0
    assert fake.painters[0].task == "inpaint" and "mask_image" in fake.pipe.calls[0]
