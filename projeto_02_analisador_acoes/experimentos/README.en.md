Versão em português: [README.md](README.md)

# Experiments

Ideas tested against human labels in [../dados_medicao/](../dados_medicao/) before becoming (or not becoming) code.

They stay here because **an unsuccessful experiment is also a result**: it prevents the same idea from returning three months later as something new.

```bash
python projeto_02_analisador_acoes/experimentos/dedup.py        # offline
python projeto_02_analisador_acoes/experimentos/regional.py     # offline
python projeto_02_analisador_acoes/experimentos/alvos.py        # collection from Google News
```

| Experiment | Question | Result | Decision |
|---|---|---|---|
| [dedup.py](dedup.py) | What rule identifies "the same news again"? | Jaccard ≥ 0.60 caught **0 of 21**; embedding (cosine ≥ 0.93) catches **11 of 21** with 1 false merger | **Adopted** |
| [alvos.py](alvos.py) | Does splitting the industry target into subtopics reduce noise? | The rate drops (60% → 36-43% in three of the four), but volume explodes from 54 to **213** headlines | **Not adopted** |
| [regional.py](regional.py) | Does a place-name list catch "news from another region"? | 6 of 9 regional stories, at the cost of **5 of 33 useful ones** | **Not adopted** |

## Why the last two were not adopted

**Splitting the sector target.** I had anticipated a "free gain", but it was not. The noise rate improves, but only on the portion I was able to measure — headlines that also appeared in the previous query and therefore already had labels. What is certain is the volume: four specific searches dig deeper into the long tail and return four times as many items, almost all regional. More items to review, even with a better percentage, creates more work, not less. And `setor-eventos` yielded 82% noise, worse than the single target: "feira OR congresso OR expo" pulls local events from every city.

**Place-name heuristic.** Flags 18 items, gets 13 right. The 5 errors are precisely the best items in the Radar: "Outback chega ao Shopping Uberaba", "Papa Johns estreia em São Paulo", "Madero confirma restaurante no Paraná". The rule cannot distinguish *news about a place* from *national news mentioning a place* — and in a monitor, missing a competitor opening a location is the most expensive mistake possible.

Its first version flagged 23 of the 33 useful items, which seemed to condemn the idea. It was my own bug: I built the location list with `split()`, so "rio de janeiro" became the loose words "de" and "do", and "Pará" became the preposition "para". It serves as a reminder that an excessively bad result warrants inspecting the code before drawing conclusions.

## What both say together

Noise does not come from broad topic queries nor from geography in the headline: it comes from **content type** (advertorials, archive pages) and **relevance to the client** (does this news from Manaus matter to a national chain? what about a bar in Curitiba?). No rule applied solely to title text resolves this, because the answer depends on who the client is.

That is exactly what [../relevancia.py](../relevancia.py) receives as context. Measuring that filter is the next step, which is why it was written before being connected.
