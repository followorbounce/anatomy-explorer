"""Group BodyParts3D 4.0 element meshes into named, classified structures.

Inputs are the text tables that ship with the dataset
(https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/):
  partof_element_parts.txt / isa_element_parts.txt   concept -> element mesh files
  partof_inclusion_relation_list.txt                 PART-OF tree (for organ systems)

Every element mesh (FJxxxx) is named after the *smallest* concept that contains it,
and elements sharing that concept are merged into one selectable structure.
"""
import collections
import re

# (system key, label, kind) — order = order in the sidebar.
SYSTEMS = [
    ("skeleton",   "Skeleton",             "bone"),
    ("muscles",    "Muscles",              "muscle"),
    ("connective", "Ligaments & fascia",   "connective"),
    ("heart",      "Heart",                "heart"),
    ("arteries",   "Arteries",             "artery"),
    ("veins",      "Veins",                "vein"),
    ("brain",      "Brain",                "brain"),
    ("nerves",     "Nerves & spinal cord", "nerve"),
    ("respiratory", "Respiratory",         "organ"),
    ("digestive",  "Digestive",            "organ"),
    ("urinary",    "Urinary",              "organ"),
    ("genital",    "Genital",              "organ"),
    ("endocrine",  "Glands & thymus",     "organ"),
    ("senses",     "Eye, ear & face",      "organ"),
    ("skin",       "Skin & body surface",  "organ"),
    ("other",      "Other",                "organ"),
]

# Name patterns, checked in order; first hit wins.
RULES = [
    ("skin",       r"\bskin\b|integument|\bnail\b|\bhair\b|cutaneous"),
    ("heart",      r"\bheart\b|atrium|ventricle|cardiac|\bvalve\b|cusp|leaflet|coronary|papillary|septum of heart|pericardi|chordae"),
    ("arteries",   r"arter|aorta|\btrunk\b.*(thyro|costo)|truncus"),
    ("veins",      r"\bvein|venous|vena\b|sinus of dura|dural venous|\bsinus\b.*(sagittal|sigmoid|transverse|straight|cavernous)|coronary sinus"),
    ("muscles",    r"muscle|tendon|sphincter|diaphragm|\bmasseter|platysma|\bpsoas|\biliacus|\bglut|\bbiceps|\btriceps|\bdeltoid|\btrapezius|\blatissimus"),
    ("connective", r"ligament|fascia|aponeurosis|retinaculum|membrane|capsule of|\bband\b|raphe|septum"),
    ("skeleton",   r"\bbone\b|vertebra|sacrum|coccyx|skull|cranium|mandible|maxilla|femur|tibia|fibula|humerus|\bradius\b|\bulna\b|scapula|clavicle|\brib\b|sternum|manubrium|patella|phalanx|metacarpal|metatarsal|carpal|tarsal|calcaneus|talus|hyoid|ilium|ischium|pubis|cartilage|\bdisc\b|meniscus|joint|sesamoid|tooth|teeth|incisor|molar|canine|premolar|\bcuboid|cuneiform|scaphoid|lunate|triquetrum|pisiform|trapezium|trapezoid|capitate|hamate|coracoid|acromion|ethmoid|sphenoid|vomer|zygomatic|nasal conch|lacrimal|palatine|occipital|parietal bone|frontal bone|temporal bone|xiphoid|hip bone|pelvis|\bcostal\b"),
    ("nerves",     r"nerve|ganglion|plexus|spinal cord|medulla spinalis|cauda equina|chiasm|optic tract|\bconus\b|filum terminale|central canal"),
    ("brain",      r"cerebr|cerebell|brain|gyrus|lobule|lobe of.*(cerebr|brain)|thalam|hippocamp|amygdal|caudate|putamen|pallidus|striatum|ventricle of brain|corpus callosum|pons\b|medulla oblongata|midbrain|hypothalam|insula|cingulate|sulcus|fornix|colliculus|tegmentum|nucleus|cortex|precuneus|fusiform|uncus|septum pellucidum|pituitary|pineal|olfactory|lingual gyrus|cuneus|operculum|opercul"),
    ("respiratory", r"lung|bronch|trachea|larynx|pleura|nasal cavity|pharynx|epiglottis|glottis|thyroid cartilage|alveol|nose|nasal"),
    ("digestive",  r"stomach|esophag|oesophag|intestin|colon|duoden|jejun|ileum|cecum|caecum|rectum|anus|anal|liver|gallbladder|pancrea|spleen|appendix|tongue|salivary|parotid|mouth|oral|palate|pharyn|alimentary|bile|hepatic|gastr|sigmoid|omentum|mesenter|peritone"),
    ("urinary",    r"kidney|renal|ureter|bladder|urethr|urinary|nephr"),
    ("genital",    r"genital|testis|prostate|penis|scrotum|epididym|seminal|vas deferens|uterus|ovary|vagina|penile"),
    ("endocrine",  r"adrenal|thyroid|parathyroid|thymus|lymph|tonsil|endocrine|node|gland"),
    ("senses",     r"\beye|eyeball|orbit|cornea|lens|retina|sclera|iris|\bear\b|cochlea|tympan|auricle|vestibul|semicircular|eyelid|lip\b|cheek|face|facial|tooth"),
]
_compiled = [(k, re.compile(p, re.I)) for k, p in RULES]

# PART-OF ancestor -> system, used when the name alone is ambiguous.
ANCESTOR_SYSTEM = {
    "alimentary system": "digestive",
    "respiratory system": "respiratory",
    "urinary system": "urinary",
    "genital system": "genital",
    "endocrine system": "endocrine",
    "integument": "skin",
    "integumentary system": "skin",
    "nervous system": "nerves",
}


# IS-A ancestor (what kind of thing it is) -> system. Checked before name patterns
# because many muscles/bones are named without the word "muscle"/"bone"
# ("external oblique", "atlas", "sternocleidomastoid").
ISA_SYSTEM = [
    ("muscle organ", "muscles"),
    ("bone organ", "skeleton"),
    ("cartilage organ", "skeleton"),
    ("artery", "arteries"),
    ("vein", "veins"),
    ("nerve", "nerves"),
    ("ligament", "connective"),
    ("fascia", "connective"),
    ("aponeurosis", "connective"),
    ("tendon", "muscles"),
]
# Named structures the IS-A tree doesn't classify (heads of muscles, arches, ...).
EXTRA = [
    ("arteries", r"palmar arch|plantar arch|celiac trunk|thyrocervical|costocervical"),
    ("muscles",  r"pronator|flexor|extensor|vastus|rectus femoris|lumbrical|interossei|adductor|abductor|coccyg|puborectalis|\blongus\b|\bbrevis\b|\bcolli\b|\bhead of\b|oblique part|\bpart of\b.*(right|left)|interspinales|intertransversarii|levatores|aryepiglotticus"),
    ("genital",  r"deferent|cavernous"),
    ("heart",    r"myocardial zone|pulmonary trunk"),
    ("digestive", r"submandibular gland|sublingual gland"),
    ("senses",   r"choroid|corona ciliaris|vitreous|trochlea of|tendinous ring"),
    ("brain",    r"commissure|stria terminalis|lamina terminalis|geniculate|mammillary|interventricular foramen|lobular segment|subarachnoid"),
]
_extra = [(k, re.compile(p, re.I)) for k, p in EXTRA]
_HEART = _compiled[1][1]
_SKIN = _compiled[0][1]


def classify(name, ancestors=(), isa_ancestors=()):
    n = name.lower()
    # Heart parts (papillary muscles, coronary arteries...) belong with the heart
    # even though IS-A calls them muscle/artery.
    if _SKIN.search(n):
        return "skin"
    if _HEART.search(n):
        return "heart"
    isa = set(isa_ancestors)
    for anc, key in ISA_SYSTEM:
        if anc in isa:
            return key
    for key, rx in _extra + _compiled:
        if rx.search(n):
            return key
    for a in ancestors:
        if a in ANCESTOR_SYSTEM:
            return ANCESTOR_SYSTEM[a]
    return "other"


def load(tables_dir):
    """Return (structures, ancestors_by_concept)."""
    concept_elems = collections.defaultdict(set)
    names = {}
    for fn in ("partof_element_parts.txt", "isa_element_parts.txt"):
        for line in open(f"{tables_dir}/{fn}", encoding="utf-8").read().splitlines()[1:]:
            c, n, e = line.split("\t")
            concept_elems[c].add(e)
            names.setdefault(c, n)

    # smallest containing concept per element (ties: shorter name, then id)
    best = {}
    for c, elems in concept_elems.items():
        for e in elems:
            key = (len(elems), len(names[c]), c)
            if e not in best or key < best[e][0]:
                best[e] = (key, c)

    groups = collections.defaultdict(list)
    for e, (_, c) in best.items():
        groups[c].append(e)

    # PART-OF ancestors (names) per concept
    par = collections.defaultdict(set)
    for line in open(f"{tables_dir}/partof_inclusion_relation_list.txt", encoding="utf-8").read().splitlines()[1:]:
        p, pn, c, cn = line.split("\t")
        par[c].add(p)
        names.setdefault(p, pn)
        names.setdefault(c, cn)

    def ancestors(c, seen=None):
        seen = seen if seen is not None else set()
        for p in par.get(c, ()):
            if p not in seen:
                seen.add(p)
                ancestors(p, seen)
        return seen

    isa_par = collections.defaultdict(set)
    isa_names = {}
    for line in open(f"{tables_dir}/isa_inclusion_relation_list.txt", encoding="utf-8").read().splitlines()[1:]:
        p, pn, c, cn = line.split("\t")
        isa_par[c].add(p)
        isa_names[p], isa_names[c] = pn, cn

    def isa_ancestors(c, seen=None):
        seen = seen if seen is not None else set()
        for p in isa_par.get(c, ()):
            if p not in seen:
                seen.add(p)
                isa_ancestors(p, seen)
        return seen

    structures = []
    for c, elems in groups.items():
        anc = [names[a].lower() for a in ancestors(c)]
        isa = [isa_names[a].lower() for a in isa_ancestors(c)]
        structures.append({
            "id": c,
            "name": names[c],
            "elements": sorted(elems),
            "system": classify(names[c], anc, isa),
        })
    structures.sort(key=lambda s: s["id"])
    return structures
