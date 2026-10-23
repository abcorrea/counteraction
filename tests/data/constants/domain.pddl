(define (domain constants)
  (:requirements :strips :typing)
  (:types loc obj)
  (:constants depot - loc pkg - obj)
  (:predicates (at ?o - obj ?l - loc) (link ?a - loc ?b - loc ?c - loc)
               (free ?l - loc) (ready) (blocked) (go) (started))
  ; A precondition that relates two variables through a constant.
  (:action move
    :parameters (?a - loc ?b - loc)
    :precondition (link ?a ?b depot)
    :effect (free ?b))
  ; An unreachable nullary precondition.
  (:action load
    :parameters (?o - obj)
    :precondition (and (at ?o depot) (blocked))
    :effect (ready))
  ; An unreachable precondition without variables.
  (:action unload
    :parameters (?l - loc)
    :precondition (and (free ?l) (at pkg ?l) (at pkg depot))
    :effect (blocked))
  ; An action without parameters.
  (:action start
    :parameters ()
    :precondition (go)
    :effect (started)))
