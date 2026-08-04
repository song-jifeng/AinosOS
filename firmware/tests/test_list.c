/*
 * AinosOS - tests/test_list.c
 * Unit tests for linked list library
 */

#include <types.h>
#include <lib/list.h>
#include <boot/boot.h>

static int test_count = 0;
static int pass_count = 0;

#define TEST_ASSERT(cond, msg) do { \
    test_count++; \
    if (!(cond)) { \
        boot_printf("  FAIL: %s\n", msg); \
    } else { \
        pass_count++; \
    } \
} while(0)

/* Test entry structure */
typedef struct {
    int value;
    struct list_node list;
} test_entry_t;

/*
 * Run all list tests
 */
void test_list(void) {
    boot_printf("\n=== List Library Tests ===\n");

    TEST_RUN("list_init/empty");
    {
        LIST_HEAD(head);
        TEST_ASSERT(list_empty(&head), "list_empty returns true for new list");
    }

    TEST_RUN("list_add");
    {
        LIST_HEAD(head);
        test_entry_t e1 = { .value = 1, .list = { NULL, NULL } };
        test_entry_t e2 = { .value = 2, .list = { NULL, NULL } };

        list_init(&e1.list);
        list_init(&e2.list);

        list_add(&head, &e1.list);
        list_add(&head, &e2.list);

        TEST_ASSERT(!list_empty(&head), "list not empty after add");
        TEST_ASSERT(head.next == &e2.list, "list_add adds to head");
        TEST_ASSERT(head.next->next == &e1.list, "list_add order correct");
    }

    TEST_RUN("list_add_tail");
    {
        LIST_HEAD(head);
        test_entry_t e1 = { .value = 1, .list = { NULL, NULL } };
        test_entry_t e2 = { .value = 2, .list = { NULL, NULL } };

        list_init(&e1.list);
        list_init(&e2.list);

        list_add_tail(&head, &e1.list);
        list_add_tail(&head, &e2.list);

        TEST_ASSERT(head.next == &e1.list, "list_add_tail adds to tail");
        TEST_ASSERT(head.prev == &e2.list, "list_add_tail prev is last");
    }

    TEST_RUN("list_remove");
    {
        LIST_HEAD(head);
        test_entry_t e1 = { .value = 1, .list = { NULL, NULL } };
        list_init(&e1.list);
        list_add(&head, &e1.list);
        list_remove(&e1.list);
        TEST_ASSERT(list_empty(&head), "list_empty after remove");
        TEST_ASSERT(e1.list.next == &e1.list, "list_remove node points to itself");
        TEST_ASSERT(e1.list.prev == &e1.list, "list_remove node points to itself");
    }

    TEST_RUN("list_pop");
    {
        LIST_HEAD(head);
        test_entry_t e1 = { .value = 1, .list = { NULL, NULL } };
        list_init(&e1.list);
        list_add(&head, &e1.list);
        struct list_node *popped = list_pop(&head);
        TEST_ASSERT(popped == &e1.list, "list_pop returns correct node");
        TEST_ASSERT(list_empty(&head), "list_empty after pop");
    }

    TEST_RUN("list_pop_tail");
    {
        LIST_HEAD(head);
        test_entry_t e1 = { .value = 1, .list = { NULL, NULL } };
        list_init(&e1.list);
        list_add_tail(&head, &e1.list);
        struct list_node *popped = list_pop_tail(&head);
        TEST_ASSERT(popped == &e1.list, "list_pop_tail returns correct node");
    }

    TEST_RUN("list_for_each");
    {
        LIST_HEAD(head);
        test_entry_t entries[5];
        int sum = 0;

        for (int i = 0; i < 5; i++) {
            entries[i].value = i + 1;
            list_init(&entries[i].list);
            list_add_tail(&head, &entries[i].list);
        }

        struct list_node *pos;
        int count = 0;
        list_for_each(pos, &head) {
            test_entry_t *entry = list_entry(pos, test_entry_t, list);
            sum += entry->value;
            count++;
        }
        TEST_ASSERT(count == 5, "list_for_each iterates all 5 entries");
        TEST_ASSERT(sum == 15, "list_for_each sum = 15");
    }

    TEST_RUN("list_for_each_entry");
    {
        LIST_HEAD(head);
        test_entry_t entries[3];
        for (int i = 0; i < 3; i++) {
            entries[i].value = i * 10;
            list_init(&entries[i].list);
            list_add_tail(&head, &entries[i].list);
        }

        test_entry_t *entry;
        int sum = 0;
        list_for_each_entry(entry, &head, list) {
            sum += entry->value;
        }
        TEST_ASSERT(sum == 30, "list_for_each_entry sum = 30");
    }

    TEST_RUN("list_length");
    {
        LIST_HEAD(head);
        test_entry_t entries[7];
        for (int i = 0; i < 7; i++) {
            list_init(&entries[i].list);
            list_add_tail(&head, &entries[i].list);
        }
        TEST_ASSERT(list_length(&head) == 7, "list_length returns 7");
    }

    TEST_RUN("list_splice");
    {
        LIST_HEAD(head1);
        LIST_HEAD(head2);
        test_entry_t e1 = { .value = 1, .list = { NULL, NULL } };
        test_entry_t e2 = { .value = 2, .list = { NULL, NULL } };

        list_init(&e1.list);
        list_init(&e2.list);
        list_add_tail(&head1, &e1.list);
        list_add_tail(&head2, &e2.list);

        list_splice(&head2, &head1);
        TEST_ASSERT(list_empty(&head2), "list_splice empties source");
        TEST_ASSERT(list_length(&head1) == 2, "list_splice merges lists");
    }

    TEST_RUN("slist operations");
    {
        struct slist_node head;
        slist_init(&head);
        TEST_ASSERT(slist_empty(&head), "slist_empty returns true");

        struct slist_node n1, n2, n3;
        n1.next = NULL;
        n2.next = NULL;
        n3.next = NULL;

        slist_add(&head, &n1);
        slist_add(&head, &n2);
        slist_add_tail(&head, &n3);

        TEST_ASSERT(!slist_empty(&head), "slist not empty");
        TEST_ASSERT(slist_length(&head) == 3, "slist_length = 3");

        struct slist_node *popped = slist_pop(&head);
        TEST_ASSERT(popped == &n2, "slist_pop returns head element");
        TEST_ASSERT(slist_length(&head) == 2, "slist_length = 2 after pop");
    }

    boot_printf("List tests: %d/%d passed\n", pass_count, test_count);
}

void run_list_tests(void) {
    test_count = 0;
    pass_count = 0;
    test_list();
}