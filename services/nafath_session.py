def get_callback_baseline(
    connection,
    identity: str
):
    """
    يحفظ آخر رقم callback موجود قبل بدء عملية نفاذ.
    بهذا نضمن لاحقًا أننا لا نستخدم تحقق قديم.
    """

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT COALESCE(MAX(id), 0)

            FROM nafath_callbacks

            WHERE PersonId = %s
            """,
            (identity,)
        )

        row = cursor.fetchone()

        if not row:
            return 0

        return int(
            row[0] or 0
        )

    finally:

        cursor.close()


def find_completed_callback(
    connection,
    identity: str,
    after_id: int = 0
):
    """
    يبحث عن تحقق نفاذ مكتمل تم إنشاؤه
    بعد بداية طلب الانسحاب الحالي فقط.
    """

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            SELECT
                id,
                request_id

            FROM nafath_callbacks

            WHERE
                PersonId = %s
                AND status = 'COMPLETED'
                AND id > %s

            ORDER BY id DESC

            LIMIT 1
            """,
            (
                identity,
                int(after_id or 0)
            )
        )

        row = cursor.fetchone()

        if not row:
            return None

        request_id = str(
            row[1] or ""
        ).strip()

        if not request_id:
            return None

        return {
            "id": int(row[0]),
            "request_id": request_id
        }

    finally:

        cursor.close()