"""The bank of dead portrait and street photographers the pipeline draws from.

Each run picks 9 at random (skipping anyone used in the last 2 runs). Each entry
describes the photographer's *technique*; prompts describe that technique
instead of naming the photographer, because image models follow concrete
visual instructions more reliably than names.

Everyone in this bank has died. Check that before adding a name.
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
    color: bool  # True if known for color work

    @property
    def label(self) -> str:
        return f"{self.name} ({self.years})"


P = Photographer
PHOTOGRAPHERS: list[Photographer] = [
    # ---------------------------------------------------------------- Latin America
    P("sergio-larrain", "Sergio Larraín", "1931–2012", "Chilean",
      "dreamlike street portraits in hard sun and deep shadow, unusual tilted framing, foreground objects "
      "cutting into the frame, mysterious mood", False),
    P("mario-cravo-neto", "Mario Cravo Neto", "1947–2009", "Brazilian",
      "bold sculptural studio portraits against a deep saturated backdrop, one hard side light, rich skin tones, "
      "a single symbolic object or flower", True),
    P("martin-chambi", "Martín Chambi", "1891–1973", "Peruvian",
      "dignified formal portraits lit by a strong window beam, deep shadows, Andean textiles and adobe walls, "
      "glass-plate tonality", False),
    P("manuel-alvarez-bravo", "Manuel Álvarez Bravo", "1902–2002", "Mexican",
      "poetic quiet scenes in bright Mexican sun, sharp shadows on plaster walls, subtle surreal touches in "
      "everyday life", False),
    P("lola-alvarez-bravo", "Lola Álvarez Bravo", "1903–1993", "Mexican",
      "intimate portraits of women in soft natural light, textured walls, rebozo shawls, quiet dignity", False),
    P("hector-garcia", "Héctor García", "1923–2012", "Mexican",
      "candid street portraits of Mexico City life, natural contrast, people framed in doorways and crowds", False),
    P("nacho-lopez", "Nacho López", "1923–1986", "Mexican",
      "staged-candid street scenes, a woman walking through a busy street turning heads, lively documentary feel", False),
    P("tina-modotti", "Tina Modotti", "1896–1942", "Italian-Mexican",
      "close, quiet portraits with soft daylight, strong simple composition, hands and faces as graphic shapes", False),
    P("kati-horna", "Kati Horna", "1912–2000", "Hungarian-Mexican",
      "poetic, slightly theatrical portraits with masks, mirrors or veils, soft surreal atmosphere", False),
    P("leo-matiz", "Leo Matiz", "1917–1998", "Colombian",
      "strong geometric compositions in bright tropical light, portraits framed by architecture and shadow", False),
    P("alberto-korda", "Alberto Korda", "1928–2001", "Cuban",
      "glamorous fashion portraits in Havana, warm Caribbean light, confident gaze, elegant 1950s styling", False),
    P("german-lorca", "Germán Lorca", "1922–2021", "Brazilian",
      "modernist São Paulo street scenes, strong shadows and reflections, figures caught in abstract light", False),
    P("horacio-coppola", "Horacio Coppola", "1906–2012", "Argentine",
      "modernist Buenos Aires streets, clean geometry, long shadows at dusk, a lone figure in the city", False),
    P("grete-stern", "Grete Stern", "1904–1999", "German-Argentine",
      "crisp Bauhaus-style studio portraits, plain backgrounds, sharp side light, direct modern gaze", False),
    P("alfredo-boulton", "Alfredo Boulton", "1908–1995", "Venezuelan",
      "elegant coastal Venezuelan light, people of Margarita island against sea, sky and whitewashed walls", False),

    # ---------------------------------------------------------------- United States
    P("saul-leiter", "Saul Leiter", "1923–2013", "American",
      "painterly color seen through rain-streaked or fogged glass and reflections, soft blur, small patches of red "
      "or yellow in a mostly dark frame", True),
    P("richard-avedon", "Richard Avedon", "1923–2004", "American",
      "stark seamless white background, flat even light, direct unsmiling gaze, every pore and stray hair sharp", False),
    P("irving-penn", "Irving Penn", "1917–2009", "American",
      "subject in a tight corner of two angled gray walls, soft north-light window, rich tonal range, elegant stillness",
      False),
    P("vivian-maier", "Vivian Maier", "1926–2009", "American",
      "square-format waist-level street portraits, candid moment on a city sidewalk, natural daylight, shop-window "
      "reflections", False),
    P("dorothea-lange", "Dorothea Lange", "1895–1965", "American",
      "documentary portrait in natural light, weathered textures, honest emotion, simple rural setting", False),
    P("lillian-bassman", "Lillian Bassman", "1917–2012", "American",
      "ethereal fashion portrait with soft blur and bleached highlights, graceful gesture, high-key glowing light",
      False),
    P("gordon-parks", "Gordon Parks", "1912–2006", "American",
      "empathetic color portrait with cinematic warm light, strong composition, everyday life seen with dignity", True),
    P("ruth-orkin", "Ruth Orkin", "1921–1985", "American",
      "candid street moment of a woman walking through a sunny European city, natural light, a story in one frame",
      False),
    P("bert-stern", "Bert Stern", "1929–2013", "American",
      "intimate glamorous portrait in soft natural light, relaxed playful expression, warm color, close and personal",
      True),
    P("garry-winogrand", "Garry Winogrand", "1928–1984", "American",
      "energetic wide-angle street photo with a tilted horizon, a woman mid-stride in hard sun, crowded city sidewalk",
      False),
    P("helen-levitt", "Helen Levitt", "1913–2009", "American",
      "playful candid New York street life in soft color, stoops and doorways, warm everyday moments", True),
    P("diane-arbus", "Diane Arbus", "1923–1971", "American",
      "square-format frontal portrait with direct on-camera flash, subject looking straight into the lens, "
      "everyday setting made strange", False),
    P("mary-ellen-mark", "Mary Ellen Mark", "1940–2015", "American",
      "intimate documentary portrait, natural light, raw honesty, the subject's own environment around her", False),
    P("bill-cunningham", "Bill Cunningham", "1929–2016", "American",
      "candid New York street-style fashion photo, a stylish woman crossing the street, daylight, motion", False),
    P("peter-hujar", "Peter Hujar", "1934–1987", "American",
      "quiet black-and-white portrait, subject reclining or still, soft window light, deep blacks, intimate stillness",
      False),
    P("arnold-newman", "Arnold Newman", "1918–2006", "American",
      "environmental portrait, the subject placed precisely within her workplace or studio, strong geometric framing",
      False),
    P("george-hurrell", "George Hurrell", "1904–1992", "American",
      "1930s Hollywood glamour portrait, sculpted butterfly lighting, glossy highlights, deep velvety shadows", False),
    P("herb-ritts", "Herb Ritts", "1952–2002", "American",
      "sculptural black-and-white portrait in bright California sun, strong shapes, wind and sand, crisp contrast",
      False),
    P("deborah-turbeville", "Deborah Turbeville", "1932–2013", "American",
      "dreamy faded fashion images, grainy washed-out color, decaying rooms, melancholy women lost in thought", True),
    P("harry-callahan", "Harry Callahan", "1912–1999", "American",
      "experimental portrait with multiple exposure and strong graphic light, figure merging with city shapes", True),
    P("james-van-der-zee", "James Van Der Zee", "1886–1983", "American",
      "elegant 1920s Harlem studio portrait, painted backdrop, refined clothing, soft hand-retouched glow", False),
    P("roy-decarava", "Roy DeCarava", "1919–2009", "American",
      "low-key black-and-white portrait, deep rich shadows, faces emerging from darkness, Harlem jazz-era mood", False),
    P("man-ray", "Man Ray", "1890–1976", "American",
      "surrealist studio portrait with solarized edges, glass tears or shadows on the face, dramatic contrast", False),
    P("imogen-cunningham", "Imogen Cunningham", "1883–1976", "American",
      "soft modernist portrait in garden light, plants and shadows, calm natural expression", False),
    P("weegee", "Weegee", "1899–1968", "Austro-Hungarian-American",
      "harsh on-camera flash at night on a city street, deep black background, candid tabloid energy", False),

    # ---------------------------------------------------------------- Immigrants to the US and Canada
    P("ernst-haas", "Ernst Haas", "1921–1986", "Austrian-American",
      "saturated Kodachrome color, glowing backlight, reflections and shallow focus turning the city into color fields",
      True),
    P("lisette-model", "Lisette Model", "1901–1983", "Austrian-American",
      "close, frank street portrait from a low angle, strong presence, bright daylight, bold contrast", False),
    P("robert-frank", "Robert Frank", "1924–2019", "Swiss-American",
      "loose grainy street photo, off-kilter framing, a woman in a diner or car window, melancholy road-trip mood",
      False),
    P("andre-kertesz", "André Kertész", "1894–1985", "Hungarian-American",
      "poetic street moment with long shadows and graceful geometry, quiet humor, soft daylight", False),
    P("philippe-halsman", "Philippe Halsman", "1906–1979", "Latvian-American",
      "lively studio portrait capturing a spontaneous moment, crisp lighting, playful energy", False),
    P("horst-p-horst", "Horst P. Horst", "1906–1999", "German-American",
      "chiaroscuro fashion portrait, sculpted spotlights and deep shadow, classical poses and elegant props", False),
    P("eve-arnold", "Eve Arnold", "1912–2012", "American-British",
      "warm intimate behind-the-scenes portrait, natural light, candid relaxed moment", False),
    P("inge-morath", "Inge Morath", "1923–2002", "Austrian-American",
      "thoughtful portrait with a touch of whimsy, natural light, the subject in her cultural setting", False),
    P("yousuf-karsh", "Yousuf Karsh", "1908–2002", "Armenian-Canadian",
      "dramatic studio lighting sculpting the face from a black background, glowing highlights, heroic stillness",
      False),
    P("fred-herzog", "Fred Herzog", "1930–2019", "German-Canadian",
      "1950s–60s Kodachrome street scenes, neon signs, warm reds and teal, people framed by storefronts and old cars",
      True),
    P("elliott-erwitt", "Elliott Erwitt", "1928–2023", "American (French-born)",
      "witty candid street moment, gentle humor, natural light, perfectly timed gesture", False),
    P("william-klein", "William Klein", "1926–2022", "American-French",
      "grainy high-contrast wide-angle street portrait, subject very close to the lens, blur and raw energy", False),

    # ---------------------------------------------------------------- Europe
    P("henri-cartier-bresson", "Henri Cartier-Bresson", "1908–2004", "French",
      "the decisive moment: a woman caught mid-step in a perfectly composed street scene, natural light, 50mm", False),
    P("robert-doisneau", "Robert Doisneau", "1912–1994", "French",
      "romantic Paris street scene, cafés and boulevards, soft daylight, tender candid moment", False),
    P("willy-ronis", "Willy Ronis", "1910–2009", "French",
      "humanist Paris photo, sunlight through a window onto a woman at home or in the street, warm intimacy", False),
    P("brassai", "Brassaï", "1899–1984", "Hungarian-French",
      "Paris at night, wet cobblestones, streetlamps and fog, a woman in a café glow", False),
    P("jacques-henri-lartigue", "Jacques Henri Lartigue", "1894–1986", "French",
      "joyful sunlit moment of a stylish woman, movement and wind, Riviera holiday light", False),
    P("jeanloup-sieff", "Jeanloup Sieff", "1933–2000", "French",
      "wide-angle black-and-white fashion portrait, dark vignetted corners, elegant long lines, moody skies", False),
    P("martine-franck", "Martine Franck", "1938–2012", "Belgian",
      "calm, balanced composition, a woman in a sunlit garden or pool with strong graphic shadows", False),
    P("sabine-weiss", "Sabine Weiss", "1924–2021", "Swiss-French",
      "humanist street portrait full of warmth, soft Paris light, an unguarded everyday moment", False),
    P("helmut-newton", "Helmut Newton", "1920–2004", "German-Australian",
      "confident fashion portrait with hard direct flash at dusk, glossy high contrast, strong pose, luxury hotel "
      "setting", False),
    P("peter-lindbergh", "Peter Lindbergh", "1944–2019", "German",
      "cinematic natural-light portrait, minimal makeup, wind in the hair, wide sky or industrial background", False),
    P("august-sander", "August Sander", "1876–1964", "German",
      "straightforward full-figure portrait, frontal pose, neutral expression, clothes and setting telling her story",
      False),
    P("julia-margaret-cameron", "Julia Margaret Cameron", "1815–1879", "British",
      "soft-focus close-up portrait in dramatic window light, flowing hair, deep shadows, painterly", False),
    P("cecil-beaton", "Cecil Beaton", "1904–1980", "British",
      "romantic society portrait, ornate theatrical backdrop, soft glamorous light, elegant gown", False),
    P("norman-parkinson", "Norman Parkinson", "1913–1990", "British",
      "outdoor fashion portrait in motion, bright daylight, exotic location, elegant and spirited", False),
    P("bill-brandt", "Bill Brandt", "1904–1983", "British",
      "high-contrast black-and-white portrait, wide-angle distortion, stark whites and inky blacks, moody coast", False),
    P("josef-sudek", "Josef Sudek", "1896–1976", "Czech",
      "soft light falling through a fogged or rain-covered window onto a quiet interior and a figure", False),
    P("luigi-ghirri", "Luigi Ghirri", "1943–1992", "Italian",
      "soft pastel color under flat overcast light, frontal balanced composition, painted walls and faded signs", True),
    P("mario-giacomelli", "Mario Giacomelli", "1925–2000", "Italian",
      "extreme high-contrast black and white, blown-out whites and pure blacks, graphic figures in snow or fields",
      False),
    P("ara-guler", "Ara Güler", "1928–2018", "Turkish",
      "atmospheric Istanbul street scene, foggy Bosphorus light, old ferries and alleys, melancholy mood", False),

    # ---------------------------------------------------------------- Asia and Africa
    P("fan-ho", "Fan Ho", "1931–2016", "Chinese (Hong Kong)",
      "single dramatic shafts of sunlight cutting through haze, long geometric shadows, figure small in a dark frame",
      False),
    P("shomei-tomatsu", "Shōmei Tōmatsu", "1930–2012", "Japanese",
      "high-contrast grainy postwar Japan, tilted framing, deep blacks, intense close portrait", False),
    P("masahisa-fukase", "Masahisa Fukase", "1934–2012", "Japanese",
      "personal, poetic black-and-white portrait, grain and movement, dusk light, melancholy and intimate", False),
    P("raghubir-singh", "Raghubir Singh", "1942–1999", "Indian",
      "rich saturated color street scene in India, layered frames, vivid saris and painted walls, warm daylight", True),
    P("homai-vyarawalla", "Homai Vyarawalla", "1913–2012", "Indian",
      "elegant mid-century documentary portrait, soft daylight, graceful composition, sari and period details", False),
    P("malick-sidibe", "Malick Sidibé", "1935–2016", "Malian",
      "joyful studio portrait against striped and patterned backdrops, checkered floor, playful pose, square format",
      False),
    P("seydou-keita", "Seydou Keïta", "1921–2001", "Malian",
      "formal daylight portrait against a bold patterned fabric backdrop, elegant clothing, calm posture", False),
    P("jd-okhai-ojeikere", "J.D. 'Okhai Ojeikere", "1930–2014", "Nigerian",
      "sculptural portrait of an elaborate braided hairstyle, plain light background, graphic shapes", False),
    P("ernest-cole", "Ernest Cole", "1940–1990", "South African",
      "empathetic documentary street portrait, natural light, strong composition, everyday dignity", False),
]

BY_SLUG = {p.slug: p for p in PHOTOGRAPHERS}


def get(slug: str) -> Photographer:
    try:
        return BY_SLUG[slug]
    except KeyError:
        raise ValueError(f"Unknown photographer {slug!r}. Run `python -m vera list` to see the bank.") from None
