/**
 * Resolve a book id to a record.
 *
 * The loaded list is the fast path — opening a row must not wait for a round
 * trip it does not need. But `#/book/<id>` is deep-linkable (UI_PLAN §5), so
 * the id may name a book on a page that was never loaded, or the app may have
 * been opened on that URL directly. Then it is fetched.
 */
import { useEffect, useState } from 'react'
import { getBook, type Book } from '../api/client'
import { useBooks } from '../lib/books'

export type BookRecord =
  | { state: 'loading' }
  | { state: 'ready'; book: Book }
  | { state: 'missing' }

export function useBookRecord(id: string | null): BookRecord {
  const books = useBooks()
  const fromList = id ? books.get(id) : undefined
  const [fetched, setFetched] = useState<BookRecord>({ state: 'loading' })

  useEffect(() => {
    if (!id || fromList) return
    let live = true
    setFetched({ state: 'loading' })
    getBook(id)
      .then((book) => live && setFetched({ state: 'ready', book: book as Book }))
      .catch(() => live && setFetched({ state: 'missing' }))
    return () => {
      live = false
    }
  }, [id, fromList])

  if (!id) return { state: 'missing' }
  // The list wins whenever it has the record, so an edit made anywhere shows
  // here immediately instead of waiting for a refetch.
  return fromList ? { state: 'ready', book: fromList } : fetched
}
