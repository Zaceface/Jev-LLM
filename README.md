# Jev-LLM

Making [Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) talk.

Jev is TypeSafe's "System One" model. It doesn't generate text — it only answers
typed questions: pick one option from a list, or give a yes/no probability.

This script makes it write anyway, one word at a time, by asking the same
question over and over: *which of these words comes next?*

```
you: Say hello to the Jev community.
Jev: hi everyone I'm Jev.

you: Your name is Jev. Say hello and introduce yourself.
Jev: hi I'm Jev nice to meet you.

you: It's raining and cold. What should I cook for dinner tonight, and why?
Jev: I think that would be soup because it's warm.

you: Make a sentence.
Jev: I am Jev.

you: Why is the sky blue?
Jev: because it is.
```

About 4–9 seconds and under a cent per reply.

## Run it

Standard library only, Python 3.8+.

```bash
export OPENROUTER_API_KEY=sk-or-...        # or put it in a .env file, see .env.example
python jev_llm.py "Your name is Jev. Say hello and introduce yourself."
```

It prints every word as it's chosen, with the runners-up:

```
  word  1: hi           44%   next best: hello 36%, I'm 11%, Jev 6%
  word  2: I'm          42%   next best: there 27%, I 12%, , 12%
  word  3: Jev         100%   next best: guy 0%, student 0%, assistant 0%
  word  4: nice         28%   next best: and 27%, . 22%, , 10%
  ...
```

The full trace of the last reply goes to `last_reply.json`.

## How it works

Each word:

1. The word list (`words.txt`, ~1,100 common words plus `, . ! ?`) is split into
   batches of 250. **Jev refuses more than 255 options in one question.**
2. All batches are asked in parallel. Each one passes on its **top 3**.
3. One final question picks between those ~15 shortlisted words.
4. Repeat until it picks `.` `!` or `?`, or hits 12 words.

That's about 5 API calls per word.

## What made the difference

Getting from word salad to sentences took three changes, same model and same
list each time:

| Version | "Your name is Jev. Say hello and introduce yourself." |
|---|---|
| 10 random words offered per step ("Make a sentence.") | **driver be may careless.** |
| Whole list, options shown as lone words | **hello Jev I is are be you fine yes.** |
| + common words and contractions added, top 3 per batch | **hi I'm Jev and is are nice.** |
| + **each option shown as the whole reply with that word added** | **hi I'm Jev nice to meet you.** |

The last one is the real trick. Shown the lone word `to`, Jev picks whatever
sounds reply-ish on its own and the grammar falls apart after three words.
Shown the phrase `hi I'm Jev nice to`, it's judging which *whole phrase* reads
best — which is exactly the kind of decision it's good at.

## Where it breaks

- **No plan.** It picks one word at a time with no idea where the sentence is
  going. For "Why is the sky blue?" the words `light` and `air` were both on the
  table (11% each), but `because it is.` was a complete sentence at every step, so
  the safe ending won. Anything that needs an explanation longer than the obvious
  next word doesn't happen.
- **Only knows the words in the list.** Before `am` was added, "I" could only be
  followed by `is`, `are` or `be` — so it tried all three. If the word it wants
  isn't there, you'll see it circling.
- **Cost scales with words, not tokens.** ~5 calls a word. Cheap per reply, slow
  compared to a real language model.

## Files

| | |
|---|---|
| `jev_llm.py` | the whole thing |
| `words.txt` | the vocabulary, one word per line — edit freely |
| `examples/` | full word-by-word traces of the replies above, including the "before" version |
| `.env.example` | where the key goes |

## Access

Jev is in early access. This uses it through
[OpenRouter's decisions endpoint](https://openrouter.ai/typesafe)
(`POST https://openrouter.ai/api/alpha/decisions`, model `~typesafe/jev-latest`),
which takes the same `{model, state, questions}` body as TypeSafe's own API.
If you have a TypeSafe key, change `ENDPOINT` to `https://api.typesafe.ai/v1/systemone`
and `MODEL` to `jev-latest`.

## Ideas to try

- A bigger or domain-specific `words.txt`
- `TOP_PER_BATCH` higher for a wider final round
- Ask Jev a second question each step ("is this reply finished?") instead of
  relying on it picking punctuation
- Beam search: keep the top 2–3 partial replies alive instead of one, and see if
  it finds the longer answers
