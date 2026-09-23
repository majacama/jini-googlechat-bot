# Comment le bot répond aux questions sur nos documents (explication simple)

## L'idée
Le bot n'a pas lu vos documents « par cœur ». On lui prépare un **index** : une sorte de très bon sommaire qui range chaque passage selon son *sens*. Quand on pose une question, le bot retrouve les passages qui ressemblent le plus à la question, puis rédige une réponse **uniquement avec ces passages**.

## Étape 1 — Préparer l'index (automatique, toutes les 15 minutes)
1. Un petit programme regarde le dossier Drive partagé « 🧠 jin-knowledge-base » (sous-dossiers compris).
2. Nouveau document ? Document modifié ? Il est relu, découpé en petits morceaux, et chaque morceau est transformé en une « empreinte de sens » (une liste de nombres).
3. Ces empreintes sont rangées dans notre base Supabase. Document supprimé du dossier ? Il disparaît de l'index.
4. Si rien n'a changé, il ne se passe rien (donc quasi aucun coût).

## Étape 2 — Répondre à une question
1. Vous écrivez au bot dans Google Chat.
2. Votre question est transformée en empreinte de sens, comparée à celles de l'index : on garde les 8 passages les plus proches.
3. Si aucun n'est assez proche, le bot dit honnêtement qu'il n'a rien trouvé.
4. Sinon, Gemini rédige la réponse **à partir de ces seuls passages** et le bot ajoute des cartes « Ouvrir dans Drive » vers les documents utilisés.

## Ce qu'il faut savoir
- **Qui voit quoi** : tout ce qui est dans le dossier partagé est accessible à tous les utilisateurs du bot. Ne mettez dans ce dossier que ce qui peut l'être.
- **Délai** : un document ajouté ou modifié est pris en compte en 15 minutes maximum.
- **Limites** : PDF scannés (images sans texte) non lus ; Google Docs, Slides, Sheets, PDF, Word, PowerPoint, Excel acceptés.
- **Jamais d'invention** : la réponse s'appuie sur les extraits ; sinon le bot s'abstient.
