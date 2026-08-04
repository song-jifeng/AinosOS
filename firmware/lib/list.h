/*
 * AinosOS - lib/list.h
 * Doubly-linked list and singly-linked list implementations
 */

#ifndef AINOS_LIB_LIST_H
#define AINOS_LIB_LIST_H

#include <types.h>
#include <macros.h>

/* Doubly-linked list node */
struct list_node {
    struct list_node *prev;
    struct list_node *next;
};

/* Initialize a list head */
#define LIST_INIT(name) { &(name), &(name) }

/* Declare a list head */
#define LIST_HEAD(name) struct list_node name = LIST_INIT(name)

/* Get pointer to the containing structure */
#define list_entry(ptr, type, member) CONTAINER_OF(ptr, type, member)

/* Iterate over a list */
#define list_for_each(pos, head) \
    for (pos = (head)->next; pos != (head); pos = pos->next)

/* Iterate over a list, safe against removal */
#define list_for_each_safe(pos, tmp, head) \
    for (pos = (head)->next, tmp = pos->next; pos != (head); \
         pos = tmp, tmp = pos->next)

/* Iterate over entries in a list */
#define list_for_each_entry(entry, head, member) \
    for (entry = list_entry((head)->next, typeof(*entry), member); \
         &entry->member != (head); \
         entry = list_entry(entry->member.next, typeof(*entry), member))

/* Iterate over entries safe against removal */
#define list_for_each_entry_safe(entry, tmp, head, member) \
    for (entry = list_entry((head)->next, typeof(*entry), member), \
         tmp = list_entry(entry->member.next, typeof(*entry), member); \
         &entry->member != (head); \
         entry = tmp, \
         tmp = list_entry(tmp->member.next, typeof(*entry), member))

/* Check if list is empty */
static inline int list_empty(const struct list_node *head) {
    return head->next == head;
}

/* Initialize a list node */
static inline void list_init(struct list_node *node) {
    node->prev = node;
    node->next = node;
}

/* Insert a node between two known nodes */
static inline void __list_add(struct list_node *node,
                               struct list_node *prev,
                               struct list_node *next) {
    next->prev = node;
    node->next = next;
    node->prev = prev;
    prev->next = node;
}

/* Add a node to the head of the list */
static inline void list_add(struct list_node *head, struct list_node *node) {
    __list_add(node, head, head->next);
}

/* Add a node to the tail of the list */
static inline void list_add_tail(struct list_node *head, struct list_node *node) {
    __list_add(node, head->prev, head);
}

/* Remove a node from between two known nodes */
static inline void __list_remove(struct list_node *prev, struct list_node *next) {
    prev->next = next;
    next->prev = prev;
}

/* Remove a node from the list */
static inline void list_remove(struct list_node *node) {
    __list_remove(node->prev, node->next);
    node->prev = node;
    node->next = node;
}

/* Remove and return the first entry */
static inline struct list_node *list_pop(struct list_node *head) {
    if (list_empty(head)) return NULL;
    struct list_node *node = head->next;
    list_remove(node);
    return node;
}

/* Remove and return the last entry */
static inline struct list_node *list_pop_tail(struct list_node *head) {
    if (list_empty(head)) return NULL;
    struct list_node *node = head->prev;
    list_remove(node);
    return node;
}

/* Get first entry */
static inline struct list_node *list_first(const struct list_node *head) {
    return list_empty(head) ? NULL : head->next;
}

/* Get last entry */
static inline struct list_node *list_last(const struct list_node *head) {
    return list_empty(head) ? NULL : head->prev;
}

/* Get list length (O(n) - use sparingly) */
static inline size_t list_length(const struct list_node *head) {
    size_t count = 0;
    const struct list_node *pos;
    list_for_each(pos, head) count++;
    return count;
}

/* Move all nodes from one list to another */
static inline void list_splice(struct list_node *from, struct list_node *to) {
    if (list_empty(from)) return;
    struct list_node *first = from->next;
    struct list_node *last = from->prev;
    first->prev = to;
    last->next = to->next;
    to->next->prev = last;
    to->next = first;
    list_init(from);
}

/* Singly-linked list */
struct slist_node {
    struct slist_node *next;
};

#define slist_entry(ptr, type, member) CONTAINER_OF(ptr, type, member)

#define slist_for_each(pos, head) \
    for (pos = (head); pos; pos = pos->next)

#define slist_for_each_safe(pos, tmp, head) \
    for (pos = (head), tmp = pos ? pos->next : NULL; \
         pos; pos = tmp, tmp = pos ? pos->next : NULL)

static inline void slist_init(struct slist_node *head) {
    head->next = NULL;
}

static inline int slist_empty(const struct slist_node *head) {
    return head->next == NULL;
}

static inline void slist_add(struct slist_node *head, struct slist_node *node) {
    node->next = head->next;
    head->next = node;
}

static inline void slist_add_tail(struct slist_node *head, struct slist_node *node) {
    struct slist_node *pos = head;
    while (pos->next) pos = pos->next;
    pos->next = node;
    node->next = NULL;
}

static inline struct slist_node *slist_pop(struct slist_node *head) {
    if (slist_empty(head)) return NULL;
    struct slist_node *node = head->next;
    head->next = node->next;
    return node;
}

static inline size_t slist_length(const struct slist_node *head) {
    size_t count = 0;
    const struct slist_node *pos = head->next;
    while (pos) { count++; pos = pos->next; }
    return count;
}

#endif /* AINOS_LIB_LIST_H */