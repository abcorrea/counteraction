(define (domain inequality)
  (:requirements :strips :typing :equality)
  (:types node)
  (:predicates (edge ?a - node ?b - node) (visited ?a - node)
               (loop ?a - node ?b - node ?c - node))
  (:action step
    :parameters (?a - node ?b - node)
    :precondition (and (edge ?a ?b) (not (= ?a ?b)))
    :effect (visited ?b))
  ; A variable that occurs twice in the same precondition.
  (:action self
    :parameters (?a - node ?c - node)
    :precondition (loop ?a ?a ?c)
    :effect (visited ?c)))
