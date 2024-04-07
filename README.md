# pIm-a-bot

🇮🇹 Versione riscritta di so-un-bot

Il bot permette di rispondere a ripetizione a tutte le domande dei corsi inseriti.

Raccolta di domande con risposta multipla utili per esercitarsi in molteplici esami!

Struttura del repository:

In data/questions sono presenti tutte le domande attualmente presenti nel bot, il nome del file corrisponde al nome del comando sul bot. Per aggiungere o correggere domande potete fare una Pull Request a questa repo.

Per i contributori:

Struttura dei file

Il bot accetta le domande nel seguente formato JSON:

```json
[
   {
      "quest": "Question 1 text",
      "image": "base64 image",
      "answers": [
         {
            "text": "First answer",
            "image": ""
         },
         {
            "text": "Second answer with image",
            "image": "base64 image"
         }
      ],
      "correct": 0
   },
   {
      "quest": "Second question without image",
      "image": "",
      "answers": [
         {
            "text": "answer without image",
            "image": ""
         },
         {
            "text": "answer without image",
            "image": ""
         }
      ],
      "correct": 1
   }
]
```
