"""
engine.py — Persona engine: session generation and branch selection.

Responsible for deciding *what* a persona will do in a given session:
  1. Which node in the topic tree to explore (select_branch)
  2. What sequence of search queries to issue (generate_query_sequence)
  3. Assembling the full SessionContext passed to plugins (build_session_context)

The weighting logic for branch selection deliberately favors nodes that haven't
been visited recently and that live higher (shallower) in the tree. This models
realistic browsing behavior — people circle back to familiar broad topics but
also drill into specifics when curiosity is fresh.
"""

import random
import uuid

from murmurate.models import PersonaState, SessionContext, TopicNode


class PersonaEngine:
    """
    Generates session plans for a persona.

    Stateless by design — all persona state lives in PersonaState. The engine
    is instantiated once and can be reused across many personas and sessions.
    """

    def _flatten_nodes(self, nodes: list[TopicNode]) -> list[TopicNode]:
        """
        Recursively flatten a topic tree into a list of all nodes.

        DFS traversal — root nodes come before their children. This ordering
        doesn't affect selection since we use weights, but it makes debugging
        and test assertions deterministic.

        Args:
            nodes: The root-level nodes (persona.topic_tree).

        Returns:
            All nodes in the tree, including all descendants.
        """
        result: list[TopicNode] = []
        for node in nodes:
            result.append(node)
            if node.children:
                result.extend(self._flatten_nodes(node.children))
        return result

    def _node_weight(self, node: TopicNode) -> float:
        """
        Compute the selection weight for a single topic node.

        Weight formula: 1/(1+query_count) * 1/(1+depth)

        This means:
          - Nodes with fewer prior queries are preferred (inverse of query_count)
          - Shallower nodes (closer to root) get a slight boost — they're broader
            and represent the core of the persona's interests

        A freshly-added node (query_count=0, depth=0) gets weight 1.0, the maximum.

        Args:
            node: The node to score.

        Returns:
            A positive float weight.
        """
        return (1.0 / (1 + node.query_count)) * (1.0 / (1 + node.depth))

    def select_branch(self, persona: PersonaState) -> TopicNode:
        """
        Choose a topic node from the persona's tree for the next session.

        Flattens the entire topic tree and performs a weighted random selection,
        favoring nodes with low query counts and shallow depth. This ensures the
        persona cycles through its interests rather than getting stuck in a loop.

        Args:
            persona: The persona whose topic tree to select from.

        Returns:
            The selected TopicNode.

        Raises:
            ValueError: If the persona's topic tree is empty.
        """
        all_nodes = self._flatten_nodes(persona.topic_tree)
        if not all_nodes:
            raise ValueError(f"Persona '{persona.name}' has an empty topic tree")

        weights = [self._node_weight(n) for n in all_nodes]
        # random.choices returns a list; [0] extracts the single selection
        selected = random.choices(all_nodes, weights=weights, k=1)[0]
        return selected

    def generate_query_sequence(
        self, persona: PersonaState, branch: TopicNode
    ) -> list[str]:
        """
        Build a logical progression of search queries for a session on this branch.

        Query count is randomized (3–8) to simulate natural session variability.
        The sequence progresses from broad to specific: early queries use the raw
        topic word, while later queries add refinements drawn from the persona's
        expertise level and depth in the topic tree.

        Specificity modifiers are chosen to reflect how a real user narrows their
        search — starting with overview terms and working toward how-to questions,
        comparisons, and specific product/technique terms.

        Args:
            persona: The persona making queries (provides expertise_level context).
            branch: The topic node driving this session.

        Returns:
            A list of 3–8 query strings, ordered from general to specific.
        """
        topic = branch.topic
        count = random.randint(3, 8)

        # Broad introductory terms — used at the start of a session
        broad_prefixes = [
            f"{topic}",
            f"introduction to {topic}",
            f"{topic} overview",
            f"what is {topic}",
            f"{topic} basics",
            f"getting started with {topic}",
            f"learn {topic}",
        ]

        # Refined terms — used toward the end of a session as the user digs deeper.
        # Expertise level shifts us toward more technical refinements: a beginner
        # (0.0) asks "for beginners", an expert (1.0) asks about advanced techniques.
        if persona.expertise_level < 0.35:
            refined_suffixes = [
                f"best {topic} for beginners",
                f"{topic} tips for beginners",
                f"how to start {topic}",
                f"easy {topic} projects",
                f"{topic} beginner guide",
                f"common {topic} mistakes beginners make",
            ]
        elif persona.expertise_level < 0.7:
            refined_suffixes = [
                f"{topic} intermediate techniques",
                f"best {topic} tools and equipment",
                f"{topic} workflow tips",
                f"how to improve at {topic}",
                f"{topic} reviews and comparisons",
                f"advanced {topic} basics",
            ]
        else:
            refined_suffixes = [
                f"advanced {topic} techniques",
                f"{topic} professional workflow",
                f"best {topic} for experts",
                f"{topic} technical deep dive",
                f"mastering {topic}",
                f"{topic} optimization strategies",
            ]

        # Depth hint: child nodes represent more specific sub-topics, so we give
        # extra context in the refined queries when the branch is deeper in the tree.
        if branch.depth > 0:
            refined_suffixes = [f"{topic} tutorial", f"best {topic}"] + refined_suffixes

        # Build the sequence: first query is always broad, remaining queries
        # progressively pull from the refined pool
        queries: list[str] = []

        # Ensure the first query is always a clean broad introduction
        queries.append(random.choice(broad_prefixes))

        # Fill subsequent slots from a mix, weighted toward refined as index grows
        for i in range(1, count):
            # As the session progresses, increasingly prefer refined queries
            use_refined = random.random() < (i / count)
            if use_refined:
                queries.append(random.choice(refined_suffixes))
            else:
                queries.append(random.choice(broad_prefixes))

        return queries

    def build_session_context(self, persona: PersonaState) -> SessionContext:
        """
        Assemble a complete SessionContext for the next persona session.

        Selects the branch to explore, generates the query sequence, and packages
        everything into a SessionContext ready for a plugin to consume.

        The session_id is a fresh UUID4 so each session is uniquely identifiable
        in logs and the database even across restarts.

        Args:
            persona: The persona for whom to build the session.

        Returns:
            A fully-populated SessionContext. prior_results is initialized to
            an empty list here — the caller (scheduler) may populate it from
            the database before handing the context to a plugin.
        """
        branch = self.select_branch(persona)
        queries = self.generate_query_sequence(persona, branch)

        return SessionContext(
            persona=persona,
            queries=queries,
            current_query_index=0,
            topic_branch=branch,
            expertise_level=persona.expertise_level,
            prior_results=[],  # Populated by scheduler from DB before plugin launch
            session_id=str(uuid.uuid4()),
        )
