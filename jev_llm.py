# -*- coding: utf-8 -*-
"""Make Jev talk.

Jev (TypeSafe's "System One" model) never generates text - it only answers
typed questions: pick one option from a list, or give a yes/no probability.
This script makes it write anyway, one word at a time, by asking it the same
question over and over: "which of these words comes next?"

How each word is picked
  1. The word list (~1,100 words) is split into batches of 250 - Jev refuses
     more than 255 options in one question.
  2. All batches are asked in parallel. Each passes on its TOP 3.
  3. One final question picks between those ~15 shortlisted words.
  4. Repeat until it picks . ! or ? (or hits MAX_WORDS).

The trick that made it work: every option is shown as the WHOLE reply so far
with that word added ("hi I'm Jev nice to"), not as a lone word ("to"). Shown
lone words, it picks whatever sounds reply-ish on its own and the grammar falls
apart after a few words. Shown whole phrases, it judges which phrase reads
best - which is exactly the kind of decision it's built for.

    export OPENROUTER_API_KEY=sk-or-...
    python jev_llm.py "Your name is Jev. Say hello and introduce yourself."

Only the standard library - no install needed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "~typesafe/jev-latest"

MAX_WORDS = 12        # hard stop for a reply
BATCH = 250           # Jev's limit is 255 options per question
TOP_PER_BATCH = 3     # how many words each batch passes to the final round
ENDERS = (".", "!", "?")


def load_key():
    """OPENROUTER_API_KEY from the environment, or from a .env file next to this script."""
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Set OPENROUTER_API_KEY (environment variable or a .env file - see .env.example)")
    return key


API_KEY = load_key()
WORDS = [w.strip() for w in open(os.path.join(HERE, "words.txt"), encoding="utf-8") if w.strip()]
for end in ENDERS:
    if end not in WORDS:
        WORDS.append(end)


def call_jev(payload):
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer %s" % API_KEY, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit("Jev returned HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))


def render(words):
    """Join words into text, no space before punctuation."""
    out = ""
    for w in words:
        out += w if (w in ",.!?" or not out) else " " + w
    return out


def state_for(prompt, so_far):
    numbered = "\n".join("  %d. %s" % (i + 1, w) for i, w in enumerate(so_far)) or "  (no words yet)"
    return (
        "You are Jev, replying to a person in a chat, one word at a time.\n\n"
        "THEIR MESSAGE: %s\n\n"
        "YOUR REPLY SO FAR: \"%s\"\n%s\n\n"
        "Rules for the reply:\n"
        "- it must be natural, grammatical English, the way a person would say it\n"
        "- it must actually answer their message\n"
        "- choose the word that comes IMMEDIATELY next - word %d of the reply\n"
        "- don't repeat a word unless the grammar needs it\n"
        "- a comma is a word; use one where a person would pause\n"
        "- end with . ! or ? as soon as the reply is a complete thought "
        "(aim for 5-10 words, never more than %d)"
        % (prompt, render(so_far), numbered, len(so_far) + 1, MAX_WORDS))


def ask(prompt, so_far, options, top):
    """One Jev question over up to 255 candidate words. Returns the top N (word, probability) and the cost."""
    resp = call_jev({
        "state": state_for(prompt, so_far),
        "model": MODEL,
        "questions": {"next": {
            "type": "choice",
            "instructions": "Each option is the reply so far with one more word added. Which one reads "
                            "as the most natural, grammatical start of a reply to their message?",
            # the key idea: show each option as the whole phrase, not the lone word
            "criteria": {"w%d" % i: render(so_far + [w]) for i, w in enumerate(options)},
        }},
    })
    probs = resp["answers"]["next"]["probabilities"]
    ranked = sorted(((options[int(k[1:])], p) for k, p in probs.items()), key=lambda kv: -kv[1])
    return ranked[:top], (resp.get("usage") or {}).get("cost", 0) or 0


def next_word(prompt, so_far):
    """Batches in parallel -> top 3 from each -> one final pick."""
    pool = [w for w in WORDS if w not in so_far or w in ",.!?"]
    batches = [pool[i:i + BATCH] for i in range(0, len(pool), BATCH)]
    with ThreadPoolExecutor(max_workers=len(batches)) as ex:
        rounds = list(ex.map(lambda b: ask(prompt, so_far, b, TOP_PER_BATCH), batches))
    shortlist = []
    for ranked, _ in rounds:
        shortlist += [w for w, _ in ranked if w not in shortlist]
    final, cost = ask(prompt, so_far, shortlist, len(shortlist))
    return final, shortlist, cost + sum(c for _, c in rounds)


def reply(prompt, verbose=True):
    so_far, steps, cost = [], [], 0.0
    t0 = time.perf_counter()
    for n in range(1, MAX_WORDS + 1):
        final, shortlist, c = next_word(prompt, so_far)
        cost += c
        pick, p = final[0]
        steps.append({"word": n, "pick": pick, "p": p, "top4": final[:4], "shortlist": shortlist})
        if verbose:
            print("  word %2d: %-10s %3.0f%%   next best: %s" % (
                n, pick, p * 100, ", ".join("%s %.0f%%" % (w, q * 100) for w, q in final[1:4])))
        so_far.append(pick)
        if pick in ENDERS:
            break
    text = render(so_far)
    if text[-1:] not in ENDERS:
        text += "."
    return {"prompt": prompt, "reply": text, "steps": steps,
            "seconds": time.perf_counter() - t0, "cost": cost}


def main():
    prompt = " ".join(sys.argv[1:]) or "Make a sentence."
    print("you: %s" % prompt)
    r = reply(prompt)
    print("\nJev: %s\n(%d words, %.1fs, $%.5f)" % (r["reply"], len(r["steps"]), r["seconds"], r["cost"]))
    with open(os.path.join(HERE, "last_reply.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2)


if __name__ == "__main__":
    main()
