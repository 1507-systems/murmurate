"""
evolution.py — TF-IDF based topic evolution for persona topic trees.

When a persona browses content, the snippets it collects are fed back through
this module to discover new subtopics. TF-IDF scoring surfaces terms that are
distinctive within the collected content (high TF-IDF) rather than generic
filler words or the parent topic itself.

The drift_rate parameter models how "adventurous" the persona is: a low value
(e.g. 0.1) accepts terms with scores above 10% of the max, while a high value
(e.g. 0.8) requires a much stronger signal — yielding fewer, more focused topics.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np

from murmurate.models import TopicNode


def extract_subtopics(
    parent_topic: str,
    content_snippets: list[str],
    max_topics: int,
    drift_rate: float,
) -> list[str]:
    """
    Extract candidate subtopics from content snippets using TF-IDF scoring.

    Args:
        parent_topic:    The topic already known — its constituent words are
                         filtered out so we don't re-surface the seed.
        content_snippets: Raw text samples collected during a browsing session.
        max_topics:      Upper bound on how many subtopics to return.
        drift_rate:      Acceptance threshold as a fraction of the maximum TF-IDF
                         score seen. Terms scoring below (max_score * drift_rate)
                         are discarded. Range [0.0, 1.0].

    Returns:
        List of subtopic strings (single terms), ordered by descending TF-IDF
        score, capped at max_topics. Returns [] if content_snippets is empty.
    """
    if not content_snippets:
        return []

    # Build the set of words to exclude: parent topic tokens + sklearn's built-in
    # English stop words. We use a union so stop_words="english" is handled
    # implicitly via the vectorizer parameter.
    parent_words = {w.lower() for w in parent_topic.split()}

    # Fit a TF-IDF matrix over the snippets.
    # - min_df=1  : include terms that appear at least once (small corpus)
    # - ngram_range=(1,1) : single terms only — multi-word subtopics get noisy fast
    # - stop_words="english" : drop common English function words automatically
    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 1),
        min_df=1,
    )
    tfidf_matrix = vectorizer.fit_transform(content_snippets)

    # Sum TF-IDF scores across all documents for each term so that terms
    # appearing (and scoring) in multiple snippets rise to the top.
    feature_names = vectorizer.get_feature_names_out()
    scores = np.asarray(tfidf_matrix.sum(axis=0)).flatten()

    # Build (term, score) pairs, filtering out parent topic words.
    term_scores = [
        (term, score)
        for term, score in zip(feature_names, scores)
        if term.lower() not in parent_words
    ]

    if not term_scores:
        return []

    max_score = max(score for _, score in term_scores)

    # Apply drift_rate as a relative threshold: only keep terms whose summed
    # TF-IDF is at least drift_rate * max_score. This lets callers tune how
    # selective the extraction is without needing to know the absolute score range.
    threshold = max_score * drift_rate
    filtered = [
        (term, score)
        for term, score in term_scores
        if score >= threshold
    ]

    # Sort descending by score and take the top max_topics results.
    filtered.sort(key=lambda x: x[1], reverse=True)
    return [term for term, _ in filtered[:max_topics]]


def evolve_topic_tree(
    node: TopicNode,
    new_subtopics: list[str],
    max_depth: int,
) -> None:
    """
    Append new subtopic children to a TopicNode in-place.

    Enforces two invariants:
      1. Depth limit — children are only added if node.depth + 1 < max_depth.
         At max depth - 1 the tree is already at the deepest allowed level.
      2. No duplicate topics — case-insensitive comparison against existing
         children prevents the same term appearing twice under the same parent.

    Args:
        node:         The parent node to expand.
        new_subtopics: Candidate topic strings to add as children.
        max_depth:    Maximum allowed depth in the tree (exclusive upper bound).
                      A node at depth (max_depth - 1) cannot have children.
    """
    # If adding a child would reach or exceed max_depth, bail out entirely.
    # node.depth + 1 is the depth the new child would have; it must be < max_depth.
    if node.depth + 1 >= max_depth:
        return

    # Build a set of already-present topic names (lower-cased) for O(1) lookup.
    existing = {child.topic.lower() for child in node.children}

    for topic in new_subtopics:
        if topic.lower() in existing:
            # Skip duplicates — the topic is already a child of this node.
            continue

        child = TopicNode(
            topic=topic,
            depth=node.depth + 1,
            children=[],
            query_count=0,
            last_used=None,
        )
        node.children.append(child)
        existing.add(topic.lower())  # Track newly added topics to prevent within-batch dupes
