# Iterasjonslogg — Nightmare Bot

Kart: `120c51da-c765-4bab-8b79-bba945a59e7c` | Seed: 7005 | 30×18 grid | 20 bots | 3 drop-off zones | 500 runder

---

## Iterasjon 1
**Dato:** 2026-03-15
**Score:** 121

### Hva som fungerte
- Grunnleggende A*-pathfinding navigerer bots korrekt rundt vegger og hyllekanter
- `global_assign` greedy auction fordeler bots på items — unngår at alle jager samme item
- Preview pre-fetching: bots henter items til neste ordre mens aktiv ordre pågår
- Priority-basert rekkefølge (leverende bots > samlende bots) gir riktig høyreprioritet
- Stuck-detection (oscillasjon + fryst) bryter deadlocks med random move
- Drop-off load balancing fordeler leverende bots på 3 soner via `zone_assignment`
- Round-0 spredning i 4 retninger (opp/høyre/ned/venstre)

### Hva som ikke fungerte / bugs funnet
- **Kritisk bug:** `deliver_action = "submit"` var feil — serveren bruker `"drop_off"` for alle vanskelighetsgrader. Resulterte i score 0 første kjøring.
- **Mange idle bots:** Stor andel bots har tomt inventory i sluttrundene. Idle-logikken er for passiv.
- **Lang leveringstid:** Alle bots spawner i [28,16] (høyre hjørne), drop-off er i [1,16] (venstre hjørne) — lang initial reisevei.
- **For sent levering:** Bot 0 satt på [12,12] med yogurt i runde 499 og rakk ikke å levere. Bots med items langt fra drop-off prioriterer ikke levering aggressivt nok.
- **Greedy assignment suboptimal:** `_greedy_assign` minimerer minste avstand per runde, men tar ikke hensyn til at en bot kan plukke opp 3 items (bare 1 item per bot assignes om gangen).
- **`nearest_drop_off` bruker manhattan, ikke A*:** Kan velge feil sone hvis vegger blokkerer den nærmeste.
- **Drop-off soner ikke bekreftet:** Koden antar 3 soner via `drop_off_zones`, men visualiseringen viser bare én `D`. Uklar om serveren sender alle sonene.

### Potensielle forbedringer til neste iterasjon
- [ ] Verifiser at `drop_off_zones` faktisk sendes av serveren med 3 soner
- [ ] Bots med inventory bør starte levering tidligere (ikke vente på at alle items er samlet)
- [ ] Assign bots til å plukke opp 2-3 items langs veien til drop-off (multi-item pathfinding)
- [ ] Idle bots etter fullført ordre bør pre-posisjonere seg nær sannsynlige item-lokasjoner for neste ordre
- [ ] Vurder A*-basert drop-off valg i stedet for manhattan
- [ ] Bots med 1+ nyttige items OG lang vei til drop-off bør velge nærmeste sone dynamisk, ikke statisk zone_assignment

---

## Iterasjon 2
**Dato:** 2026-03-15
**Scores:** 37 → 50 → 58 (regressjon, deretter delvis gjenoppretting)

### Endringer forsøkt
- Multi-item routes i `_greedy_assign` (Phase 2: forleng bot-ruter med opptil 3 items)
- `walls_base` vs `walls` separasjon — A* og `adjacent_walkable` bruker nå ulike vegg-sett
- 60 %-terskel for preview pre-fetch (bots henter neste ordre først når 60 % av aktiv ordre er dekket)
- Brute-force assignment wrappet til liste-format: `{bid: [(item, adj)]}` for uniform interface

### Bugs funnet

#### Bug 1 (kritisk): `adjacent_walkable` kalt med `walls_base` i stedet for `walls`
**Symptom:** Score falt fra 121 til 37. Bots sto stille nesten hele spillet.
**Årsak:** `adjacent_walkable(item["position"], walls_base, ...)` returnerer item-posisjoner som "gangbare" naboer (siden items ikke er i `walls_base`). A* bruker `walls` (inkl. items) som vegger → A*-sti til disse posisjonene returnerer tom liste → bots velger `wait`.
**Berørte steder:**
- `assignment.py`: astar_cache-beregning og Phase 2-route-extension
- `decision.py`: assignment-branch else-klausul (linje 123), greedy fallback, preview pre-fetch
**Fix:** Alle `adjacent_walkable`-kall byttet tilbake til `walls` (med items).

#### Bug 2 (moderat): 60 %-terskel for preview pre-fetch
**Symptom:** 13–15 av 20 bots idle fra starten (orden har 5–7 items, resten er ledige med en gang).
**Årsak:** Terskelen `order_completion >= 0.6` hindret idle bots fra å pre-fetche neste ordre.
**Fix:** Terskel fjernet. Preview pre-fetch er alltid aktiv: `if preview and len(inventory) < 3:`.

#### Bug 3 (latent): Phase 2 multi-item routing aktiveres aldri i praksis
**Årsak:** Ordrer har færre items enn antall bots (5–7 items, 20 bots). `type_remaining` tømmes allerede i Phase 1, så Phase 2-loopen har ingenting å gjøre. Multi-item routing er implementert men ubrukt.
**Status:** Ikke fikset ennå — krever redesign.

### Hva som fungerte
- Brute-force wrapping til liste-format fungerer korrekt (uniform interface med greedy)
- Multi-item route-struktur i decision.py itererer riktig over `[(item, adj), ...]`
- Greedy auction Phase 1 (første item per bot) fungerer som forventet

### Status ved slutt av iterasjon
- Siste kjøring med alle fixer: score **149** (opp fra 121 i iterasjon 1)
- Alle `walls_base`-referanser fikset, preview-terskel fjernet

### Potensielle forbedringer til neste iterasjon
- [ ] Kjør på nytt med alle `walls_base`-feil fikset og preview-terskel fjernet — forventet score > 121
- [ ] Verifiser at `drop_off_zones` faktisk sendes med 3 soner (visualisering viser bare én `D`)
- [ ] Redesign multi-item routing: assign en bot flere items fra start, ikke kun forlenge etter Phase 1
- [ ] Bots uten assignment og uten inventory bør spre seg mot senter av kartet (ikke vente ved spawn)
- [ ] Vurder A*-basert drop-off-valg der manhattan gir feil sone pga. vegger

---

## Iterasjon 3
**Dato:** 2026-03-15
**Scores:** 90 → 108 (begge regredierer fra 149)

### Endringer forsøkt

#### Endring 1: End-game mode
Lever umiddelbart hvis `rounds_remaining <= dist_to_drop + 3`. Forhindrer bots fra å strande med items ved spill-slutt (3 bots, 8 items strandet i iterasjon 2).

#### Endring 2: Lever med 1 item når orden nesten ferdig
`if has_useful and len(ctx.global_remaining) <= 1: deliver`. Antatt at dette ville fremskynde ordrekompletering.

#### Endring 3: Fjernet round-0 spread
Erstattet med home-position navigasjon for idle bots.

#### Endring 4: Home-position idle navigasjon
Idle bots navigerer til forhåndstildelte hjemposisjoner (bots 0-9 → y=9-korridor, bots 10-19 → y=15-korridor) istedenfor å vente.

### Bugs/problemer funnet

#### Bug 1 (kritisk): "Lever med 1 item" halverte throughput
**Symptom:** Score falt fra 149 til 90.
**Årsak:** Når `global_remaining <= 1` sender alle bots med useful items seg til drop-off med kun 1 item. Med 27-cellers reisevei = 54 runder ekstra overhead per bot per ordre (3 separate 1-item-turer vs 1 tre-item-tur). Bots leverer ikke 3 items samlet.
**Fix:** Fjernet sjekken.

#### Bug 2 (moderat): Home-position navigasjon ga regressjon
**Symptom:** Score 108 etter fjerning av "lever med 1 item", fortsatt under 149.
**Årsak:** Home-position A* kjøres for alle idle bots hver runde (10+ A* beregninger ekstra). Sendte dessuten bots med `home_y=16, home_x=1` direkte til drop-off-posisjonen → bots satt fast i "steg-vekk"-loop ved drop-off.
**Fix:** Fjernet home-position-logikken.

#### Bug 3 (liten): Round-0 spread sendte 5 bots til samme celle
**Årsak:** Original spread (`bot_id % 4`) sendte bots 0,4,8,12,16 alle til [28,15] og bots 1,5,9,13,17 til [27,16]. Server avviste kollisjoner, kun 1 bot per gruppe beveget seg.
**Fix:** Ny round-0 spread: partalls-ID → opp, odde-ID → venstre. Halverer kollisjonene.

### Status ved slutt av iterasjon
- End-game mode beholdt (korrekt logikk, hjelper med strandede bots)
- Round-0 spread gjenopprettet og fikset
- Home-position og "lever med 1 item" fjernet
- Kjørt med ny token etter fixes

### Potensielle forbedringer til neste iterasjon
- [ ] Verifiser at fikset kode gir score ≥ 149
- [ ] Undersøk hvorfor score-rate er flat (~30 poeng/100 runder) — flaskehals er throughput, ikke antall bots
- [ ] Bedre initial spredning: bots trenger 10-20 runder å komme seg ut av spawn-hjørnet [28,16]
- [ ] Vurder å øke early-delivery-terskel fra 3 til 5-7 celler for bots med 2+ items

---

## Iterasjon 4
**Dato:** 2026-03-15
**Scores:** 120 → 148

### Endringer forsøkt

#### End-game mode (beholdt fra iterasjon 3)
`if inventory and has_useful and rounds_remaining <= dist_to_drop + 3: deliver`
Fikser de 3 strandede botene ved spill-slutt.

#### Preview-adjacent grab før levering
Ny sjekk: Før en bot leverer pga. `order_fully_covered`, sjekkes om det ligger et preview-item adjacent. Hvis ja, plukkes det opp først — maksimerer items per delivery-tur.

#### Round-0 spread: tilbakestilt til original (bot_id % 4)
Forsøket med `bot_id % 2` (halvparten opp, halvparten venstre) viste seg å sende 10 bots til samme celle og forverret kollisjoner. Original spread (4 retninger, bots mot vegger hopper over) ble gjenopprettet.

### Hva som fungerte
- Preview-adjacent grab er nøytral/svakt positiv (149 → 148, innenfor natural variasjon)
- End-game mode forhindrer strandede bots de siste rundene

### Observasjoner om natural variasjon
Scores mellom kjøringer: 120, 130, 148, 149. Variasjon ±15 % tyder på at ulike game-instanser har ulik item-distribusjon/ordre-timing. Algoritmen er stabil rundt 130–150.

### Potensielle forbedringer til neste iterasjon
- [ ] Throughput-analyse: bots leverer bare ~150 items over 500 runder, teoretisk maks ~1200. 88 % ineffektivitet skyldes spawn-trengsel og idle-tid
- [ ] Scoring-forståelse: 1 poeng per delivery-tur? Per item? Per ordre? Avklarhet hjelper prioritering
- [ ] Grab preview-items nær bots path til drop-off (innenfor 5 celler), ikke bare adjacent
- [ ] Vurder å aldri levere med < 2 items med mindre dist ≤ 5 eller end-game

---

## Iterasjon 5
**Dato:** 2026-03-15
**Scores:** 70, 110 (begge regresjon fra 149)

### Endringer forsøkt

#### Endring 1: Home-position pre-posisjonering (y=9/y=15, x=6..24)
**Resultat:** Score 70 (regressjon)
**Årsak:** Idle bots som navigerer til korridor-hjemposisjoner blokkerer de samme korridorene som aktive bots bruker for å nå shelf-items. 10+ bots i y=9-korridoren skaper massiv trafikk. Alle bots starter i [28,16] og skal til hjemposisjoner = eskalert spawn-trengsel i tidlige runder.

#### Endring 2: Assignment-caching (recompute kun ved item/ordre-endring)
**Resultat:** Score 110 (regressjon)
**Årsak:** Når en bot plukker opp et item, endres `collecting_bots`-settet. Nye assignments sendes bot midt i navigasjon til nytt item → osillasjoner og bortkastet bevegelse. Caching forutsetter stabile bot-konfigurasjoner, men collecting_bots-settet endres kontinuerlig.

### Viktige lærdommer
1. **Idle bots i korridorer blokkerer aktive bots** — enhver "spre idle bots"-mekanisme som sender dem til navigasjonskorridorer er kontraproduktiv
2. **Assignment-caching skaper oscillasjon** — global_assign MÅ kjøres hver runde for å holde assignments konsistente med bot-posisjoner
3. **Natural variasjon er ±15 poeng** — score 120-149 er alle innenfor normalvariasjonen for nåværende algoritme
4. **Score-tak på ~149**: med 500 runder, 1 drop-off sone og 7 items/ordre kan vi IKKE holde 20 bots produktive — strukturell begrensning

### Fundamental bottleneck-analyse
- 7 items/ordre + 4 preview = 11 produktive bots → 9 bots alltid idle (45 % idle-rate)
- Drop-off ved [1,16], spawn ved [28,16]: 27-cellers one-way trip = lang retur-tid
- Maks teoretisk score med nåværende arkitektur: ~200-250 (ikke ~1400)
- For å nå ~1400: trenger sannsynligvis 3 aktive drop-off soner ELLER fundamentalt annen spill-mekanikk

### Potensielle veier fremover
- [ ] Verifiser hva `drop_off_zones` faktisk inneholder i nightmare — er det virkelig 3 soner?
- [ ] Les full game state JSON (print første runde) — skjult data vi ikke utnytter?
- [ ] Utforsk om bots kan levere preview-items mens aktiv ordre pågår (uten å vente)
- [ ] Undersøk om "submit" vs "drop_off" faktisk gjør noe i nightmare (ubrukt action?)
- [ ] **Stabil baseline: 148-149** — ikke introduser nye endringer uten klar positiv logikk

---

## Iterasjon 6
**Dato:** 2026-03-15
**Score:** 151 (ny baseline)

### Funn fra debug-logging (runde 0 JSON)
- **`drop_off_zones`: [[1,16], [15,16], [27,16]]** — 3 soner bekreftet! Sone [27,16] er 1 celle fra spawn [28,16]
- **`total_orders`: 500** — 500 ordrer skal fullføres i løpet av spillet
- **`items_count`: 144** — 144 items på gulvet fra starten
- Visualiseringen viser bare 1 D, men serveren sender 3 soner

### Endring: Zone-aware assignment
**Ny kostfunksjon:** `total_trip_cost = dist(bot→item_adj) + dist(item→nærmeste_sone)`

Bots nær [27,16] får nå tildelt items på høyre side av kartet → leverer til [27,16] på 1–2 steg.
Bots i midten → sone [15,16]. Bots på venstre → sone [1,16].

**Bug funnet underveis:** `zones`-variabelen var definert ETTER `global_assign`-kallet. Fikset ved å flytte definisjonen opp.

### Resultat
Score 151 vs baseline 149 (+2 totalt, men +18-20 i runde 250-400):
| Runde | Gammel | Ny | Diff |
|---|---|---|---|
| 250 | 59 | 78 | **+19** |
| 300 | 80 | 99 | **+19** |
| 400 | 111 | 129 | **+18** |

Mid-game er tydelig bedre. Sluttscore konvergerer fordi bots er langt fra drop-off i siste runder.

### Neste prioriteringer
- [ ] Bots nær [27,16] bør ALLTID levere til [27,16], ikke balanseres vekk — zone_assignment for delivering bots bør respektere nærhet mer
- [ ] Med 500 totale ordrer og 144 items — respawner items? Undersøk item-count mellom runder
- [ ] End-game bug: mange bots er fremdeles ved spawn [28,16] siste runder — de bør ha levert til [27,16] lenge siden
- [ ] Scoring uklar: 151/500 ordrer = 30 % ordrekompletering. Hva gir de beste lagene?

---

## Iterasjon 7
**Dato:** 2026-03-15
**Scores:** 102 → 121 → 92 (alle regredierer fra 151-baseline)

### Endringer forsøkt

#### Endring 1: Sentralisert preview-assignment via global_assign (full A*)
**Resultat:** Score 102 (regressjon)
**Årsak:** Preview-assignede bots fikk `ctx.assignment` satt til preview-items. I `else: if ctx.assignment:` branchen i decision_impl fulgte disse botene preview-items fremfor å hjelpe med aktive ordre-items. Preview-prioritet overstyrte aktiv-ordre-innsamling.

#### Endring 2: Separert preview_assignment-felt i DecisionContext
**Resultat:** Score 121 (fortsatt lavere enn 151)
**Årsak:** Separering løste overordnings-buggen, men score er innenfor naturalvariasjon (120-151). Extra `global_assign`-kall la til ~260 A*-beregninger per runde på toppen av opprinnelig 560. Mulig timeout-press.

#### Endring 3: Lettvekts greedy manhattan-auction (uten A*)
**Resultat:** Score 92 (verste regressjon)
**Årsak:** Auction sorterer bots etter ID (ikke avstand til items), gir suboptimal fordeling. Eksisterende per-bot manhattan pre-fetch i decision_impl er allerede optimal for formålet.

### Viktige lærdommer
1. **Per-bot preview pre-fetch i decision_impl er allerede korrekt og velfungerende** — sentralisert assignment hjelper ikke og kan forstyrre
2. **Enhver tilleggskode i websocket.py main loop bør vurderes med tanke på timing** — 560 A* kall/runde er allerede marginalt
3. **Naturalvariasjon ±15 gjør det vanskelig å skille ekte forbedringer fra støy uten mange kjøringer**

### Status ved slutt av iterasjon
- Alle preview_assignment-endringer reversert
- Kode er tilbake til iterasjon 6-baseline (score 151)

### Neste prioriteringer
- [ ] Undersøk om items respawner mellom runder (print item-count per runde)
- [ ] Print item-posisjoner i runde 0 for å forstå kartets item-distribusjon
- [ ] Øk avg items/delivery fra 2.5 → 3.0: plukk opp preview-items på veien til drop-off (distance ≤ 2 og "on-the-way")
- [ ] Undersøk om A* er flaskehalsen (timing) ved å måle tid per runde

---

## Iterasjon 8
**Dato:** 2026-03-15
**Score:** 160 (ny rekord!)

### Diagnostikkfunn (fra iterasjon 7)
- **Item distribusjon:** x<10: 48, x10-20: 60, x>=20: 36. Items kun til x=25 — zone [27,16] har ingen items direkte inntil
- **Item respawn:** min=max=144 alle runder → items respawner umiddelbart når de plukkes opp
- **Timing:** 5-8 slow rounds (>150ms) av 500 — timing er IKKE flaskehalsen
- **21 item-typer**, de fleste med 8 eksemplarer på gulvet
- **Duplikat-targeting er en funksjon, ikke en bug** — 13 bots som konkurrerer om 7 items gir fault-tolerance: hvis en assigned bot blokkeres av vegger, tar en annen over

### Endringer
- **Preberegnet `full_walls` og `wall_set` én gang per runde** i websocket.py → eliminerer 10 000+ redundante list-konkatenering og 200 000+ set-konstruksjoner per spill
- **Preberegnet `all_inv_flat`** én gang per runde, delt via ctx
- **`astar`, `next_action_toward`, `adjacent_walkable`** tar nå valgfri `wall_set`-parameter for å unngå å gjenskape set ved hvert kall
- `assigned_types`-filter forsøkt men forårsaket score 6 → reversert (se under)

### Bugs/regresjon forsøkt
#### `assigned_types`-filter (score 6)
Forsøkt å hindre unassignede bots fra å konkurrere om typer som allerede er assigned. Resulterte i score 6.
**Årsak:** Hvis en assigned bot ikke klarer å nå sitt item (omgitt av vegger/items), er det ingen backup-bot som plukker opp typen. Med filteret er duplikat-targeting-"avfallet" faktisk nødvendig fault-tolerance.

### Resultat
- Score 160 (opp fra 149-151 baseline)
- 50 leveringer (opp fra 33-42)
- 5 slow rounds (ned fra 7-8)

### Bekreftelses-kjøring
Score 111 (40 leveringer, 2.58 items/delivery). Variasjon 111–160 → sann baseline ~135, opp fra ~130.
Høy variasjon skyldes hvilke item-typer ordren trenger og hvilke soner bots tilfeldighvis ender nær.

### Neste prioriteringer
- [ ] Items respawner umiddelbart → idle bots kan alltid finne noe å plukke opp, men vi kjenner ikke fremtidige ordrer
- [ ] Vanskelig å redusere variasjon uten å kjenne ordresekvensen
- [ ] Potensielt: plukk opp items for preview på vei til drop-off (innen 2 celler og "på veien")
- [ ] Potensielt: vurder om bots bør pre-posisjonere seg nærmere item-midtpunktet etter levering
