(define (domain conditional)
  (:requirements :strips :typing :conditional-effects)
  (:types item)
  (:predicates (has ?i - item) (marked ?i - item) (used ?i - item))
  (:action mark
    :parameters (?i - item)
    :precondition (has ?i)
    :effect (when (has ?i) (marked ?i)))
  (:action use
    :parameters (?i - item)
    :precondition (marked ?i)
    :effect (used ?i)))
