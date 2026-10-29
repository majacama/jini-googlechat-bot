#!/usr/bin/env bash
# Fait tourner l'agent Chat sous son propre compte (agent-formulaire-gchat@…) au lieu du compte
# Compute par défaut, puis retire à ce dernier le rôle Éditeur du projet (2026-10-18).
# Depuis la racine du dépôt, en deux temps, avec un test du bot dans Chat entre les deux :
#   bash deploy/compte-dedie.sh basculer    # droits du compte dédié + nouvelle révision (même image)
#   bash deploy/compte-dedie.sh nettoyer    # retire Éditeur et les droits devenus inutiles du compte par défaut
#   bash deploy/compte-dedie.sh annuler     # remet le service sous le compte par défaut (avant « nettoyer »)
set -euo pipefail

PROJECT=admin-jin-fr
REGION=europe-west1
SERVICE=agent-formulaire-gchat
AGENT=agent-formulaire-gchat@$PROJECT.iam.gserviceaccount.com
DEFAUT=531758065224-compute@developer.gserviceaccount.com

case "${1:-}" in
  basculer)
    # Firestore (conversations) : l'Éditeur du compte par défaut le couvrait.
    gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$AGENT" \
      --role=roles/datastore.user --condition=None >/dev/null
    echo "Firestore : roles/datastore.user donné à l'agent."
    gcloud secrets add-iam-policy-binding start-endpoint-token --project "$PROJECT" \
      --member="serviceAccount:$AGENT" --role=roles/secretmanager.secretAccessor --condition=None >/dev/null
    echo "Lecture de start-endpoint-token donnée à l'agent."
    # Le code obtient ses jetons Chat et Directory en agissant au nom de CHAT_SERVICE_ACCOUNT,
    # c'est-à-dire lui-même désormais : il lui faut ce droit sur son propre compte.
    gcloud iam service-accounts add-iam-policy-binding "$AGENT" --project "$PROJECT" \
      --member="serviceAccount:$AGENT" --role=roles/iam.serviceAccountTokenCreator --condition=None >/dev/null
    echo "L'agent peut obtenir des jetons pour son propre compte."
    gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" --service-account "$AGENT"
    echo "Bascule faite. Écris au bot dans Google Chat (une question, puis une demande de dossier client)."
    ;;
  nettoyer)
    actuel=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
      --format="value(spec.template.spec.serviceAccountName)" | tr -d '\r')
    if [ "$actuel" != "$AGENT" ]; then echo "Le service tourne encore sous $actuel : lance d'abord « basculer »." >&2; exit 1; fi
    gcloud projects remove-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEFAUT" \
      --role=roles/editor --condition=None >/dev/null
    echo "Rôle Éditeur retiré au compte par défaut (il garde ses rôles de construction)."
    gcloud iam service-accounts remove-iam-policy-binding "$AGENT" --project "$PROJECT" \
      --member="serviceAccount:$DEFAUT" --role=roles/iam.serviceAccountTokenCreator --condition=None >/dev/null
    echo "Le compte par défaut ne peut plus agir au nom de l'agent."
    for s in admin-jin-bot-token start-endpoint-token; do
      gcloud secrets remove-iam-policy-binding "$s" --project "$PROJECT" \
        --member="serviceAccount:$DEFAUT" --role=roles/secretmanager.secretAccessor --condition=None >/dev/null
      echo "Lecture de $s retirée au compte par défaut."
    done
    echo "Nettoyage terminé."
    ;;
  annuler)
    gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" --service-account "$DEFAUT"
    echo "Service remis sous le compte par défaut."
    ;;
  *)
    echo "Usage : bash deploy/compte-dedie.sh basculer|nettoyer|annuler" >&2; exit 1 ;;
esac
