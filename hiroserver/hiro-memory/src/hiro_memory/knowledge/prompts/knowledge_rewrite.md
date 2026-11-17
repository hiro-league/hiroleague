Rewrite the user's question into one clean, standalone search query.

Fix typos and normalize informal or dialectal phrasing into clear formal language, but do NOT change the meaning or add information that is not in the question.

If a conversation is provided, resolve references (pronouns, 'the second one', 'his brother') against it so the query stands alone without the conversation.

Copy proper nouns, names, dates, and identifiers VERBATIM into `keywords` — never translate or 'correct' a name.

Set `knowledge_needed` to false when the message is just a greeting, farewell, thanks, acknowledgement, or small talk and clearly does not ask for stored information; otherwise true. Do not invent facts or answer the question.

Respond with a JSON object containing exactly these fields:
- `standalone_query` (string): the rewritten standalone search query.
- `keywords` (array of strings): proper nouns, names, dates, and identifiers copied verbatim.
- `knowledge_needed` (boolean): false only for greetings/thanks/small talk, otherwise true.
- `entities` (array of strings): named entities the question asks about (people, places, organizations) and qualified relational mentions like 'my sister' or 'mom'; empty when the question references no specific entity (e.g. 'what is photosynthesis?').