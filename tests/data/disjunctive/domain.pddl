(define (domain disjunctive)
  (:requirements :strips :typing :disjunctive-preconditions)
  (:types item)
  (:predicates (red ?i - item) (big ?i - item) (picked ?i - item))
  ; The normalizer splits this action into one copy per disjunct.
  (:action pick
    :parameters (?i - item)
    :precondition (or (red ?i) (big ?i))
    :effect (picked ?i)))
