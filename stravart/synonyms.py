"""Maps user-typed animal/object terms to the strav.art category slug they live in.

The site has a fixed set of category pages under /home/{slug}. Users type free-form
queries ("dog", "puppy", "doggo"), so we maintain a hand-curated synonym table and
seed it into the DB at build time. Search code reads from the DB table, not this
module, so the seed can be hot-edited later without redeploying the scraper.
"""

from __future__ import annotations

# Canonical strav.art category slugs (under /home/{slug})
CATEGORIES: tuple[str, ...] = (
    "animation",
    "birds",
    "burbing",
    "cats-dogs",
    "dinosaurs",
    "elephants",
    "fiction",
    "food-drink",
    "geography",
    "hearts",
    "holidays",
    "insects",
    "mammals",
    "misc",
    "people",
    "plants",
    "reptiles",
    "sea-life",
    "shapes",
    "snails",
    "sport",
    "transport",
    "words-numbers",
)

# user term (lowercase) -> category slug
SYNONYMS: dict[str, str] = {
    # cats-dogs
    "cat": "cats-dogs",
    "cats": "cats-dogs",
    "kitty": "cats-dogs",
    "kitten": "cats-dogs",
    "dog": "cats-dogs",
    "dogs": "cats-dogs",
    "puppy": "cats-dogs",
    "puppies": "cats-dogs",
    "doggo": "cats-dogs",
    "yorkie": "cats-dogs",
    "labrador": "cats-dogs",
    "poodle": "cats-dogs",
    "pet": "cats-dogs",
    "pets": "cats-dogs",
    # birds
    "bird": "birds",
    "birds": "birds",
    "owl": "birds",
    "duck": "birds",
    "chicken": "birds",
    "rooster": "birds",
    "penguin": "birds",
    "parrot": "birds",
    "swan": "birds",
    "flamingo": "birds",
    "eagle": "birds",
    # dinosaurs
    "dinosaur": "dinosaurs",
    "dinosaurs": "dinosaurs",
    "dino": "dinosaurs",
    "trex": "dinosaurs",
    "t-rex": "dinosaurs",
    "raptor": "dinosaurs",
    "stegosaurus": "dinosaurs",
    # elephants
    "elephant": "elephants",
    "elephants": "elephants",
    # mammals
    "mammal": "mammals",
    "mammals": "mammals",
    "horse": "mammals",
    "pig": "mammals",
    "cow": "mammals",
    "sheep": "mammals",
    "lion": "mammals",
    "tiger": "mammals",
    "bear": "mammals",
    "rabbit": "mammals",
    "bunny": "mammals",
    "mouse": "mammals",
    "rat": "mammals",
    "fox": "mammals",
    "wolf": "mammals",
    "deer": "mammals",
    "kangaroo": "mammals",
    "monkey": "mammals",
    "giraffe": "mammals",
    "squirrel": "mammals",
    # insects
    "insect": "insects",
    "insects": "insects",
    "bug": "insects",
    "bugs": "insects",
    "bee": "insects",
    "butterfly": "insects",
    "ant": "insects",
    "spider": "insects",
    "ladybug": "insects",
    # reptiles
    "reptile": "reptiles",
    "reptiles": "reptiles",
    "snake": "reptiles",
    "lizard": "reptiles",
    "turtle": "reptiles",
    "tortoise": "reptiles",
    "crocodile": "reptiles",
    "alligator": "reptiles",
    "gecko": "reptiles",
    # sea-life
    "fish": "sea-life",
    "shark": "sea-life",
    "whale": "sea-life",
    "dolphin": "sea-life",
    "octopus": "sea-life",
    "crab": "sea-life",
    "lobster": "sea-life",
    "seahorse": "sea-life",
    "jellyfish": "sea-life",
    "sealife": "sea-life",
    "sea-life": "sea-life",
    "ocean": "sea-life",
    # snails
    "snail": "snails",
    "snails": "snails",
    "slug": "snails",
    # plants
    "plant": "plants",
    "plants": "plants",
    "flower": "plants",
    "tree": "plants",
    "leaf": "plants",
    # hearts / holidays
    "heart": "hearts",
    "love": "hearts",
    "valentine": "hearts",
    "christmas": "holidays",
    "santa": "holidays",
    "easter": "holidays",
    "halloween": "holidays",
    "pumpkin": "holidays",
    # people
    "person": "people",
    "people": "people",
    "face": "people",
    "stickman": "people",
    # transport
    "car": "transport",
    "bike": "transport",
    "bicycle": "transport",
    "plane": "transport",
    "boat": "transport",
    "ship": "transport",
    "train": "transport",
    # sport
    "ball": "sport",
    "football": "sport",
    "soccer": "sport",
    "basketball": "sport",
    # food
    "food": "food-drink",
    "drink": "food-drink",
    "pizza": "food-drink",
    "burger": "food-drink",
    "beer": "food-drink",
    "coffee": "food-drink",
    "cake": "food-drink",
    "icecream": "food-drink",
    "ice-cream": "food-drink",
    # shapes / misc fallthrough
    "shape": "shapes",
    "shapes": "shapes",
    "star": "shapes",
    "circle": "shapes",
    "square": "shapes",
    "misc": "misc",
}


def resolve_category(term: str) -> str | None:
    """Resolve a user-typed term to a strav.art category slug, or None."""
    if not term:
        return None
    t = term.strip().lower()
    if t in CATEGORIES:
        return t
    return SYNONYMS.get(t)
