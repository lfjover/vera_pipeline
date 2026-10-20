"""Dead painters and visual artists for the VeraSynth Art account.

Prompts describe technique instead of naming the artist. Everyone here has died.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Photographer:
    slug: str
    name: str
    years: str
    nationality: str
    style: str
    color: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.years})"


P = Photographer
PHOTOGRAPHERS: list[Photographer] = [
    P("hilma-af-klint", "Hilma af Klint", "1862–1944", "Swedish",
      "large abstract diagrams of spirals, petals and pastel circles on a pale ground, mystical symmetry", True),
    P("gustav-klimt", "Gustav Klimt", "1862–1918", "Austrian",
      "gold leaf patterns, flattened ornamental bodies, mosaic flowers and spirals", True),
    P("vincent-van-gogh", "Vincent van Gogh", "1853–1890", "Dutch",
      "thick swirling impasto, intense yellow and blue, visible directional brushstrokes", True),
    P("frida-kahlo", "Frida Kahlo", "1907–1954", "Mexican",
      "symbolic Mexican flora, flat bold color, thorns and ribbons, small intimate scale", True),
    P("rembrandt", "Rembrandt", "1606–1669", "Dutch",
      "deep brown darkness and a warm pool of light on cloth or metal", True),
    P("johannes-vermeer", "Johannes Vermeer", "1632–1675", "Dutch",
      "cool daylight from a left window, quiet tabletop, pearl grey and pale yellow", True),
    P("claude-monet", "Claude Monet", "1840–1926", "French",
      "broken touches of color, water and garden light, soft edges, no hard outline", True),
    P("edgar-degas", "Edgar Degas", "1834–1917", "French",
      "cropped space, unexpected angle, pastel dust, off-center movement", True),
    P("paul-cezanne", "Paul Cézanne", "1839–1906", "French",
      "flat patches of color, apples and folded cloth, structure over prettiness", True),
    P("georges-seurat", "Georges Seurat", "1859–1891", "French",
      "tiny dots of pure color, still waterfront, hushed pointillist light", True),
    P("henri-matisse", "Henri Matisse", "1869–1954", "French",
      "flat unmixed color shapes, bold pattern, cut-paper simplicity", True),
    P("pablo-picasso", "Pablo Picasso", "1881–1973", "Spanish",
      "cubist planes, an object seen from two angles, charcoal line and ochre", True),
    P("georgia-okeeffe", "Georgia O'Keeffe", "1887–1986", "American",
      "a flower or bone filling the frame, smooth gradients, desert clarity", True),
    P("edward-hopper", "Edward Hopper", "1882–1967", "American",
      "lonely architecture, hard sunlight, an empty room by a window", True),
    P("mark-rothko", "Mark Rothko", "1903–1970", "American",
      "two or three soft-edged rectangles of luminous color on a stained field", True),
    P("jackson-pollock", "Jackson Pollock", "1912–1956", "American",
      "poured and dripped enamel, all-over web of lines, raw canvas showing through", True),
    P("wassily-kandinsky", "Wassily Kandinsky", "1866–1944", "Russian",
      "floating circles and diagonals, musical color, white breathing space", True),
    P("kazimir-malevich", "Kazimir Malevich", "1879–1935", "Russian",
      "severe geometry, a few colored planes on an open white field", True),
    P("piet-mondrian", "Piet Mondrian", "1872–1944", "Dutch",
      "black grid, rectangles of red yellow and blue on a white ground", True),
    P("joan-miro", "Joan Miró", "1893–1983", "Spanish",
      "biomorphic signs, a few black lines, stars and primary blobs on an empty field", True),
    P("salvador-dali", "Salvador Dalí", "1904–1989", "Spanish",
      "precise dream objects, long shadows, melting forms, a tiny horizon", True),
    P("rene-magritte", "René Magritte", "1898–1967", "Belgian",
      "ordinary objects in a quiet contradiction, deadpan daylight", True),
    P("paul-klee", "Paul Klee", "1879–1940", "Swiss-German",
      "small signs like a child's map, thin line, muted squares", True),
    P("egon-schiele", "Egon Schiele", "1890–1918", "Austrian",
      "angular ink line, raw contour, spare background", True),
    P("william-turner", "J. M. W. Turner", "1775–1851", "British",
      "light dissolving the horizon, sea and sun, yellow atmosphere", True),
    P("caspar-david-friedrich", "Caspar David Friedrich", "1774–1840", "German",
      "a vast foggy landscape, romantic silence, a pale enormous sky", True),
    P("francisco-goya", "Francisco Goya", "1746–1828", "Spanish",
      "uneasy forms emerging from black, harsh late manner, no prettiness", True),
    P("caravaggio", "Caravaggio", "1571–1610", "Italian",
      "a hard spotlight on fruit and cloth against pure black", True),
    P("leonardo-da-vinci", "Leonardo da Vinci", "1452–1519", "Italian",
      "soft smoky transitions, a study of drapery or a machine, warm brown ground", True),
    P("sandro-botticelli", "Sandro Botticelli", "1445–1510", "Italian",
      "flowing outline, pale tempera, a floral meadow, graceful curves", True),
    P("hieronymus-bosch", "Hieronymus Bosch", "1450–1516", "Dutch",
      "crowded miniature hybrids in a landscape, precise tiny incidents", True),
    P("katsushika-hokusai", "Katsushika Hokusai", "1760–1849", "Japanese",
      "ukiyo-e line, a great wave, flat Prussian blue, bold cropped design", True),
    P("utagawa-hiroshige", "Utagawa Hiroshige", "1797–1858", "Japanese",
      "rain over a bridge, flat woodblock color, travelers small in weather", True),
    P("tarsila-do-amaral", "Tarsila do Amaral", "1886–1973", "Brazilian",
      "smooth tropical volumes, cactus and machine, clean surreal color", True),
    P("wifredo-lam", "Wifredo Lam", "1902–1982", "Cuban",
      "hybrid mask and plant forms, sharp shards, Afro-Caribbean signs", True),
    P("leonora-carrington", "Leonora Carrington", "1917–2011", "British-Mexican",
      "mythic creatures, alchemical symbols, eerie narrative precision", True),
    P("remedios-varo", "Remedios Varo", "1908–1963", "Spanish-Mexican",
      "slender invented machines, fine hatching, a moonlit workshop", True),
    P("amrita-sher-gil", "Amrita Sher-Gil", "1913–1941", "Hungarian-Indian",
      "simplified figures in rich color, quiet monumental pose", True),
    P("agnes-martin", "Agnes Martin", "1912–2004", "American",
      "faint hand-drawn pencil grid, almost white, pale bands of wash", True),
    P("yayoi-kusama-excluded", "do not use", "1929–1929", "none", "none", True),
]
PHOTOGRAPHERS = [p for p in PHOTOGRAPHERS if p.slug != "yayoi-kusama-excluded"]
BY_SLUG = {p.slug: p for p in PHOTOGRAPHERS}


def get(slug: str) -> Photographer:
    try:
        return BY_SLUG[slug]
    except KeyError:
        raise ValueError(f"Unknown artist {slug!r}. Run `python -m vera list` to see the bank.") from None
