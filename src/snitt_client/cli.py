"""Thin JSON CLI over SnittClient (stdio-friendly)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from snitt_client.client import SnittClient, SnittClientError
from snitt_client.session import SessionConfigError


def _print_json(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return exit_code


def _load_text_arg(text: str | None, text_file: str | None) -> str:
    if text_file:
        return Path(text_file).read_text(encoding="utf-8")
    if text is None:
        raise SystemExit("Provide --text or --text-file")
    return text


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI argument parser.

    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(prog="snitt", description="Snitt.hu sheet client (JSON output)")
    parser.add_argument("--config", help="Cookie file path (default: ~/.snitt-hu-downloader.cfg or SNITT_COOKIE)")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_parser = sub.add_parser("fetch", help="GET and parse a film sheet")
    fetch_parser.add_argument("--slug", required=True)

    resolve_tag = sub.add_parser("resolve-tag", help="Resolve open tag via open_tags API")
    resolve_tag.add_argument("--name", required=True)

    resolve_genre = sub.add_parser("resolve-genre", help="Resolve műfaj via genres API")
    resolve_genre.add_argument("--name", required=True)

    plan_tag = sub.add_parser("plan-tag", help="Dry-run plan for open tag add")
    plan_tag.add_argument("--slug", required=True)
    plan_tag.add_argument("--name", required=True)

    plan_genre = sub.add_parser("plan-genre", help="Dry-run plan for műfaj add")
    plan_genre.add_argument("--slug", required=True)
    plan_genre.add_argument("--name", required=True)

    plan_description = sub.add_parser("plan-description", help="Dry-run plan for description add")
    plan_description.add_argument("--slug", required=True)
    plan_description.add_argument("--text")
    plan_description.add_argument("--text-file")

    apply_tag = sub.add_parser("apply-tag", help="Save open tag (requires --allow-save)")
    apply_tag.add_argument("--slug", required=True)
    apply_tag.add_argument("--name", required=True)
    apply_tag.add_argument("--allow-save", action="store_true")

    apply_genre = sub.add_parser("apply-genre", help="Save műfaj (requires --allow-save)")
    apply_genre.add_argument("--slug", required=True)
    apply_genre.add_argument("--name", required=True)
    apply_genre.add_argument("--allow-save", action="store_true")

    apply_description = sub.add_parser("apply-description", help="Save description (requires --allow-save)")
    apply_description.add_argument("--slug", required=True)
    apply_description.add_argument("--text")
    apply_description.add_argument("--text-file")
    apply_description.add_argument("--allow-save", action="store_true")

    watchings = sub.add_parser("list-watchings", help="List filmnézések (read-only)")
    watchings.add_argument("--username", default="balage")
    watchings.add_argument("--year", type=int)
    watchings.add_argument("--type", dest="watching_type", choices=["movies", "shortfilms", "series", "miniseries", "talkshows"])
    watchings.add_argument("--tag")
    watchings.add_argument("--place", choices=["cinema", "other"])

    series_span = sub.add_parser("series-watch-span", help="First/latest watch times for a series slug")
    series_span.add_argument("--slug", required=True)
    series_span.add_argument("--username", default="balage")
    series_span.add_argument("--years", required=True, help="Comma-separated years to scan, e.g. 2024,2025")
    series_span.add_argument("--type", dest="watching_type", default="series")

    ratings = sub.add_parser("list-ratings", help="List értékelések with stars and optional review text")
    ratings.add_argument("--username", default="balage")
    ratings.add_argument("--page", type=int, default=1)
    ratings.add_argument("--order")
    ratings.add_argument("--rating", type=int)
    ratings.add_argument("--is-reviewed", dest="is_reviewed", choices=["1", "0"])

    rating_detail = sub.add_parser("fetch-rating", help="Fetch one értékelés detail by id")
    rating_detail.add_argument("--review-id", type=int, required=True)

    watching_form = sub.add_parser("fetch-watching-form", help="GET mark-watched modal (episodes / movie fields)")
    watching_form.add_argument("--slug", required=True)

    plan_watched = sub.add_parser("plan-mark-watched", help="Dry-run plan for Most néztem…")
    plan_watched.add_argument("--slug", required=True)
    plan_watched.add_argument("--episode-id", type=int)
    plan_watched.add_argument("--episode-label")
    plan_watched.add_argument("--season-number", type=int)
    plan_watched.add_argument("--episode-number", type=int)
    plan_watched.add_argument("--review")
    plan_watched.add_argument("--spoiler", action="store_true")
    plan_watched.add_argument("--in-cinema", action="store_true")

    apply_watched = sub.add_parser("apply-mark-watched", help="Save mark-watched (requires --allow-save)")
    apply_watched.add_argument("--slug", required=True)
    apply_watched.add_argument("--episode-id", type=int)
    apply_watched.add_argument("--episode-label")
    apply_watched.add_argument("--season-number", type=int)
    apply_watched.add_argument("--episode-number", type=int)
    apply_watched.add_argument("--review")
    apply_watched.add_argument("--spoiler", action="store_true")
    apply_watched.add_argument("--in-cinema", action="store_true")
    apply_watched.add_argument("--allow-save", action="store_true")

    plan_fav = sub.add_parser("plan-favorite", help="Dry-run favorite heart add/remove")
    plan_fav.add_argument("--slug", required=True)
    plan_fav.add_argument("--want-favorite", required=True, choices=["true", "false"])

    apply_fav = sub.add_parser("apply-favorite", help="Save favorite heart (requires --allow-save)")
    apply_fav.add_argument("--slug", required=True)
    apply_fav.add_argument("--want-favorite", required=True, choices=["true", "false"])
    apply_fav.add_argument("--allow-save", action="store_true")

    plan_rating = sub.add_parser("plan-set-rating", help="Dry-run 1–10 personal star rating")
    plan_rating.add_argument("--slug", required=True)
    plan_rating.add_argument("--stars", type=int, required=True)

    apply_rating = sub.add_parser("apply-set-rating", help="Save personal stars (requires --allow-save)")
    apply_rating.add_argument("--slug", required=True)
    apply_rating.add_argument("--stars", type=int, required=True)
    apply_rating.add_argument("--allow-save", action="store_true")

    plan_review = sub.add_parser("plan-add-review", help="Dry-run Új értékelés text review")
    plan_review.add_argument("--slug", required=True)
    plan_review.add_argument("--text")
    plan_review.add_argument("--text-file")
    plan_review.add_argument("--spoiler", action="store_true")

    apply_review = sub.add_parser("apply-review", help="Save text review (requires --allow-save)")
    apply_review.add_argument("--slug", required=True)
    apply_review.add_argument("--text")
    apply_review.add_argument("--text-file")
    apply_review.add_argument("--spoiler", action="store_true")
    apply_review.add_argument("--allow-save", action="store_true")

    plan_del_w = sub.add_parser("plan-delete-watching", help="Dry-run delete one filmnézés")
    plan_del_w.add_argument("--watching-id", type=int, required=True)

    apply_del_w = sub.add_parser("apply-delete-watching", help="Delete filmnézés (requires --allow-save)")
    apply_del_w.add_argument("--watching-id", type=int, required=True)
    apply_del_w.add_argument("--allow-save", action="store_true")

    plan_del_r = sub.add_parser("plan-delete-review", help="Dry-run delete one értékelés")
    plan_del_r.add_argument("--review-id", type=int, required=True)

    apply_del_r = sub.add_parser("apply-delete-review", help="Delete értékelés (requires --allow-save)")
    apply_del_r.add_argument("--review-id", type=int, required=True)
    apply_del_r.add_argument("--allow-save", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI entrypoint.

    :param list[str] | None argv: Optional argument vector.
    :rtype: int
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config) if getattr(args, "config", None) else None
    try:
        with SnittClient(config_path=config_path) as client:
            if args.command == "fetch":
                sheet = client.fetch_sheet(args.slug)
                return _print_json({"ok": True, "sheet": sheet.to_dict()})
            if args.command == "resolve-tag":
                tag = client.resolve_open_tag(args.name, exact_name=args.name)
                return _print_json({"ok": True, "tag": tag.to_dict()})
            if args.command == "resolve-genre":
                tag = client.resolve_genre(args.name, exact_name=args.name)
                return _print_json({"ok": True, "genre": tag.to_dict()})
            if args.command == "plan-tag":
                plan = client.plan_add_tag(args.slug, args.name)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "plan-genre":
                plan = client.plan_add_genre(args.slug, args.name)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "plan-description":
                text = _load_text_arg(args.text, args.text_file)
                plan = client.plan_add_description(args.slug, text)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-tag":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_add_tag(args.slug, args.name)
                result = client.save_tagging(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "apply-genre":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_add_genre(args.slug, args.name)
                result = client.save_tagging(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "apply-description":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                text = _load_text_arg(args.text, args.text_file)
                plan = client.plan_add_description(args.slug, text)
                result = client.save_description(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "list-watchings":
                events = client.list_watchings(
                    username=args.username,
                    year=args.year,
                    watching_type=args.watching_type,
                    tag=args.tag,
                    place=args.place,
                )
                return _print_json({"ok": True, "count": len(events), "watchings": [event.to_dict() for event in events]})
            if args.command == "series-watch-span":
                years = [int(part.strip()) for part in args.years.split(",") if part.strip()]
                span = client.series_watch_span(
                    args.slug,
                    username=args.username,
                    years=years,
                    watching_type=args.watching_type,
                )
                return _print_json({"ok": True, "span": span.to_dict()})
            if args.command == "list-ratings":
                is_reviewed = None
                if args.is_reviewed == "1":
                    is_reviewed = True
                elif args.is_reviewed == "0":
                    is_reviewed = False
                entries, meta = client.list_ratings(
                    username=args.username,
                    page=args.page,
                    order=args.order,
                    rating=args.rating,
                    is_reviewed=is_reviewed,
                )
                return _print_json(
                    {
                        "ok": True,
                        "count": len(entries),
                        "meta": meta,
                        "ratings": [entry.to_dict() for entry in entries],
                    }
                )
            if args.command == "fetch-rating":
                entry = client.fetch_rating(args.review_id)
                return _print_json({"ok": True, "rating": entry.to_dict()})
            if args.command == "fetch-watching-form":
                form = client.fetch_watching_form(args.slug)
                return _print_json({"ok": True, "form": form.to_dict()})
            if args.command == "plan-mark-watched":
                plan = client.plan_mark_watched(
                    args.slug,
                    episode_id=args.episode_id,
                    episode_label=args.episode_label,
                    season_number=args.season_number,
                    episode_number=args.episode_number,
                    review=args.review,
                    spoiler=args.spoiler,
                    in_cinema=args.in_cinema,
                )
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-mark-watched":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_mark_watched(
                    args.slug,
                    episode_id=args.episode_id,
                    episode_label=args.episode_label,
                    season_number=args.season_number,
                    episode_number=args.episode_number,
                    review=args.review,
                    spoiler=args.spoiler,
                    in_cinema=args.in_cinema,
                )
                result = client.save_watching(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "plan-favorite":
                plan = client.plan_favorite(args.slug, args.want_favorite == "true")
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-favorite":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_favorite(args.slug, args.want_favorite == "true")
                result = client.save_favorite(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "plan-set-rating":
                plan = client.plan_set_rating(args.slug, args.stars)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-set-rating":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_set_rating(args.slug, args.stars)
                result = client.save_rating(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "plan-add-review":
                text = _load_text_arg(args.text, args.text_file)
                plan = client.plan_add_review(args.slug, text, spoiler=args.spoiler)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-review":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                text = _load_text_arg(args.text, args.text_file)
                plan = client.plan_add_review(args.slug, text, spoiler=args.spoiler)
                result = client.save_review(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "plan-delete-watching":
                plan = client.plan_delete_watching(args.watching_id)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-delete-watching":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_delete_watching(args.watching_id)
                result = client.save_delete_watching(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            if args.command == "plan-delete-review":
                plan = client.plan_delete_review(args.review_id)
                return _print_json({"ok": True, "dry_run": True, "plan": plan.to_dict()})
            if args.command == "apply-delete-review":
                if not args.allow_save:
                    return _print_json({"ok": False, "error": "Refusing write without --allow-save"}, exit_code=2)
                plan = client.plan_delete_review(args.review_id)
                result = client.save_delete_review(plan, allow_save=True)
                return _print_json({"ok": result.ok, "plan": plan.to_dict(), "result": result.to_dict()}, exit_code=0 if result.ok else 1)
            return _print_json({"ok": False, "error": f"Unknown command {args.command}"}, exit_code=2)
    except (SessionConfigError, SnittClientError, httpx_error_types()) as exc:
        return _print_json({"ok": False, "error": str(exc)}, exit_code=1)


def httpx_error_types() -> tuple:
    """Return httpx exception types for CLI catch.

    :rtype: tuple
    """
    import httpx

    return (httpx.HTTPError,)


if __name__ == "__main__":
    raise SystemExit(main())
