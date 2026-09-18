Ez a mappa automatikusan töltődik fel a GitHub Actions workflow által minden
nap: ide kerülnek a generált digest-képek (images/latest/0.jpg, 1.jpg, ...)
és egy manifest.json, amire az e-mail küldő lépés (src/main.py send)
támaszkodik. Nincs vele kézi teendőd - ne törölj belőle semmit, és ne
szerkeszd kézzel, mert a workflow úgyis felülírja minden futásnál.
