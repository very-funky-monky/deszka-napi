Ez a mappa a Te hét saját sablonképedet tartalmazza, egy az egyben:

    template_szinhaz.jpg
    template_mozgokep.jpg
    template_tanc.jpg
    template_opera.jpg
    template_zene.jpg
    template_kepzomuveszet.jpg
    template_konyv.jpg

A src/renderer.py ezeket tölti be alapként, és csak a cikk borítóképét
(a fotó-helyre) és a cím/szerző szövegét illeszti rájuk - a fejléc, a
logó, a panel-textúra és a rovat-címke pontosan az marad, ami a fájlban
van. Ha frissítenél egy sablont, ugyanazzal a névvel, ugyanolyan
945x2048-as méretben cseréld le a megfelelő fájlt.

Megjegyzés: a template_szinhaz.jpg és a template_mozgokep.jpg jelenleg
ugyanazt a türkiz színvilágot használja - ha ez nem szándékos, egy saját
Mozgókép-sablonnal ez egyszerűen lecserélhető.
