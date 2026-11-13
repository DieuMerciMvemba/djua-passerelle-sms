# Transport HTTP

Le transport est s?lectionn? par `BACKEND_TRANSPORT=mqtt|http|both` ; `mqtt` reste le d?faut. Les param?tres ci-dessous sont lus depuis `config/gateway.env`.

| Variable | D?faut | R?le |
| --- | --- | --- |
| `HTTP_BACKEND_URL` | vide | URL HTTP(S) compl?te, route incluse ; requise en mode `http` ou `both` |
| `HTTP_EVENTS_URL` | vide | URL des ?v?nements D2E ; vide signifie `HTTP_BACKEND_URL` |
| `HTTP_AUTH_TOKEN` | vide | Ajoute `Authorization: Bearer <token>` si renseign? |
| `HTTP_EXTRA_HEADERS_JSON` | `{}` | Objet JSON de paires nom/valeur d?en-t?tes |
| `HTTP_TIMEOUT_SECONDS` | `5` | D?lai maximal synchrone d?une requ?te |
| `HTTP_VERIFY_TLS` | `true` | V?rification du certificat TLS |
| `HTTP_RETRY_BASE_SECONDS` | `2` | Base du backoff exponentiel |
| `HTTP_RETRY_MAX_SECONDS` | `300` | D?lai maximal de retry |
| `HTTP_BATCH_LIMIT` | `10` | Nombre maximal de POST par cycle |

Chaque POST utilise `Content-Type: application/json`, `X-DJUA-Topic` et `Idempotency-Key`. Son corps est exactement `payload_json` persist? dans l?outbox, sans nouvelle normalisation. La cl? est `message_id` pour D2, sinon `outbox-<id>`.

Un statut 2xx acquitte HTTP. Les erreurs r?seau, timeouts, 5xx, 408 et 429 sont retent?s avec backoff. Les autres 4xx sont journalis?s en erreur et retent?s au d?lai maximal ; aucune erreur HTTP n?abandonne d?finitivement la ligne.

En mode `both`, MQTT et HTTP ont chacun leur ?tat et leurs retries. Le statut global passe ? `PUBLISHED` apr?s l?acquittement de tous les transports activ?s. Un acquittement MQTT emp?che sa republication pendant le retry HTTP.

Un topic finissant par `/geofence/events` est trait? comme ?v?nement urgent D2E, passe avant la t?l?m?trie dans le lot HTTP et utilise `HTTP_EVENTS_URL` si elle est renseign?e. Le payload et la cl? d?idempotence restent inchang?s.

La route et l?authentification du backend DJUA ne sont pas confirm?es ici ; la compatibilit? end-to-end reste ? valider.

## Brancher le backend plus tard

1. Renseigner `HTTP_BACKEND_URL` avec l?URL compl?te fournie par le backend.
2. Renseigner ?ventuellement `HTTP_AUTH_TOKEN` ou les en-t?tes requis.
3. Passer `BACKEND_TRANSPORT` ? `http` ou `both`.
