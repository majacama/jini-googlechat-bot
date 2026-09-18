# Comment le bot va chercher dans le Drive — explication simple

Ce document explique, sans jargon technique, le système qu'on s'apprête à construire
pour que Jin Investigator Agent puisse répondre à des questions en cherchant dans les
documents Drive de JIN. Pour le détail technique et l'historique des essais, voir
`docs/SPEC-Jin-Investigator-Cible-V2.md` section 6.

## Le besoin, en une phrase

Quelqu'un écrit une question au bot dans Google Chat (« on a un budget pour l'AO
Renault ? »), et le bot doit chercher la réponse dans les documents Drive de
l'entreprise, sans jamais montrer à quelqu'un un document auquel il n'a pas droit.

## Le problème qu'on a rencontré

Le service qu'on a essayé en premier (celui de Google, « Vertex AI Search ») refuse
tout simplement qu'un programme automatique (le bot) fasse une recherche à sa place.
Il exige que la recherche soit faite **au nom d'une vraie personne**, pour pouvoir
vérifier ce que cette personne a le droit de voir.

Le souci, c'est que pour « emprunter l'identité » de quelqu'un de cette façon, Google
nous a d'abord demandé un droit bien trop large — l'équivalent d'un passe-partout
qui ouvrirait toutes les portes de l'entreprise, pas seulement l'armoire à documents.
On a refusé ce passe-partout et cherché une clé plus précise.

## L'idée retenue : une autorisation ciblée, comme un badge à usage unique

On va utiliser un mécanisme différent, plus précis : à chaque question posée au bot,
celui-ci va demander à Google **un badge temporaire qui représente exactement la
personne qui a posé la question**, mais qui ne sert **qu'à lire des fichiers Drive** —
rien d'autre. Ce badge :

- ne permet pas d'écrire, de partager ou de supprimer quoi que ce soit ;
- ne permet pas d'accéder à autre chose que Drive (pas aux e-mails, pas à l'agenda,
  pas aux autres services Google) ;
- ne dure que le temps de la recherche, puis n'est plus utilisable.

Techniquement, ce badge est fabriqué par Google lui-même à la demande du bot — le
bot ne détient jamais de clé secrète permanente, il demande juste « fabrique-moi un
badge pour untel, valable une heure, juste pour lire ses fichiers Drive ». C'est la
même logique que ce qu'on a déjà mis en place pour que le bot sache qui écrit dans
le chat (résolution de l'identité) — on l'étend simplement à Drive.

## Ce qu'il faut faire une seule fois, avant que ça marche

Un administrateur (toi) doit dire à Google, une bonne fois pour toutes : *« j'autorise
le bot à demander ce type de badge, mais seulement pour lire des fichiers Drive, rien
de plus »*. C'est une autorisation qui se donne dans la console d'administration
Google Workspace, pas dans le code. Une fois donnée, le bot peut demander ce badge
pour n'importe quel collaborateur, automatiquement, sans repasser par la console à
chaque fois.

## Le déroulé complet d'une question

1. Quelqu'un écrit une question dans le chat.
2. Le bot comprend que c'est une question documentaire (pas une demande de process).
3. Le bot demande à Google le badge temporaire pour cette personne précise.
4. Avec ce badge, le bot cherche dans Drive les documents qui répondent à la question
   — et Google ne renvoie que ce que cette personne a le droit de voir, pas plus.
5. Le bot prend les extraits pertinents, et répond dans le chat avec des « cards » :
   un titre, un court extrait, et un bouton pour ouvrir le document dans Drive.

## Deux niveaux de recherche possibles

**Niveau simple** : le bot utilise la recherche native de Drive (celle qui trouve des
fichiers par mots-clés, comme quand on tape dans la barre de recherche Drive
soi-même). Rapide à mettre en place, mais moins fine — elle rate parfois une réponse
formulée différemment de la question.

**Niveau plus riche** : en plus de la recherche par mots-clés, le bot découpe le
contenu des documents et les compare au sens de la question plutôt qu'aux mots exacts
(ce qu'on appelle une recherche « sémantique »). Plus pertinent, mais plus long à
construire — ça demande de traiter les documents à l'avance et de les stocker dans
une base adaptée. On peut commencer par le niveau simple et enrichir plus tard sans
tout refaire, puisque l'autorisation (le badge) et le circuit de la question restent
les mêmes dans les deux cas.

## Ce qui reste à vérifier une fois construit

- Que l'autorisation donnée dans la console Google fonctionne bien telle qu'on
  l'attend (on a déjà eu deux mauvaises surprises avec Google sur ce sujet précis,
  donc on vérifiera avant de considérer que c'est acquis).
- Qu'une personne qui n'a pas accès à un document précis ne le voit vraiment jamais
  apparaître dans une réponse du bot — un test avec un collègue non-administrateur,
  pas seulement avec ton propre compte.
