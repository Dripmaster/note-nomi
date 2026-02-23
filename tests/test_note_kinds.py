import unittest

from app.note_kinds import classify_url, compute_note_kinds, extract_urls


class NoteKindsTests(unittest.TestCase):
    def test_extract_urls_trims_trailing_punctuation(self) -> None:
        urls = extract_urls("watch this https://youtu.be/abc) now")
        self.assertEqual(urls, ["https://youtu.be/abc"])
        self.assertEqual(classify_url(urls[0]), "youtube")

    def test_compute_note_kinds_multilabel_plain_text_and_youtube(self) -> None:
        result = compute_note_kinds(
            {
                "sourceUrl": "kakaotalk://in-chat/123",
                "contentFull": "shared video https://www.youtube.com/watch?v=abc",
                "summaryShort": "",
                "summaryLong": "",
            }
        )
        self.assertEqual(result["primary_kind"], "plain_text")
        self.assertEqual(result["kinds"], ["plain_text", "youtube"])

    def test_compute_note_kinds_instagram_post_vs_reel(self) -> None:
        post = compute_note_kinds(
            {
                "sourceUrl": "https://www.instagram.com/p/ABC123/",
                "contentFull": "",
                "summaryShort": "",
                "summaryLong": "",
            }
        )
        reel = compute_note_kinds(
            {
                "sourceUrl": "https://www.instagram.com/reel/ZZZ999/",
                "contentFull": "",
                "summaryShort": "",
                "summaryLong": "",
            }
        )
        self.assertEqual(post["primary_kind"], "instagram_post")
        self.assertEqual(post["kinds"], ["instagram_post"])
        self.assertEqual(reel["primary_kind"], "instagram_reel")
        self.assertEqual(reel["kinds"], ["instagram_reel"])

    def test_compute_note_kinds_threads_detection(self) -> None:
        result = compute_note_kinds(
            {
                "sourceUrl": "https://www.threads.net/@alice/post/ABCDEF",
                "contentFull": "",
                "summaryShort": "",
                "summaryLong": "",
            }
        )
        self.assertEqual(result["primary_kind"], "threads")
        self.assertEqual(result["kinds"], ["threads"])

    def test_compute_note_kinds_other_link_detection(self) -> None:
        result = compute_note_kinds(
            {
                "sourceUrl": "https://example.com/blog/post",
                "contentFull": "",
                "summaryShort": "",
                "summaryLong": "",
            }
        )
        self.assertEqual(result["primary_kind"], "other_link")
        self.assertEqual(result["kinds"], ["other_link"])

    def test_compute_note_kinds_uses_stable_kind_order(self) -> None:
        result = compute_note_kinds(
            {
                "sourceUrl": "kakaotalk://in-chat/999",
                "contentFull": "https://www.youtube.com/watch?v=abc https://example.com/path",
                "summaryShort": "",
                "summaryLong": "",
            }
        )
        self.assertEqual(result["kinds"], ["plain_text", "youtube", "other_link"])


if __name__ == "__main__":
    _ = unittest.main()
