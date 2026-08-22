package com.example.seenflowfixture;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Bundle;
import android.view.MotionEvent;
import android.view.View;

public final class MainActivity extends Activity {
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        boolean welcomeInitiallyVisible = getIntent().getBooleanExtra("welcomeInitiallyVisible", false);
        boolean swipeMode = getIntent().getBooleanExtra("swipeMode", false);
        boolean spatialMode = getIntent().getBooleanExtra("spatialMode", false);
        setContentView(new FixtureView(welcomeInitiallyVisible, swipeMode, spatialMode));
    }

    private final class FixtureView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final boolean welcomeInitiallyVisible;
        private final boolean swipeMode;
        private final boolean spatialMode;
        private boolean tapped;
        private boolean swiped;
        private float touchDownY;

        FixtureView(boolean welcomeInitiallyVisible, boolean swipeMode, boolean spatialMode) {
            super(MainActivity.this);
            this.welcomeInitiallyVisible = welcomeInitiallyVisible;
            this.swipeMode = swipeMode;
            this.spatialMode = spatialMode;
            setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
            setBackgroundColor(Color.WHITE);
        }

        private RectF button() {
            float centerX = getWidth() / 2f;
            float centerY = getHeight() / 2f;
            return new RectF(centerX - 300, centerY - 90, centerX + 300, centerY + 90);
        }

        private RectF spatialButton(float centerY) {
            float centerX = getWidth() * 0.70f;
            return new RectF(centerX - 140, centerY - 80, centerX + 140, centerY + 80);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (spatialMode) {
                if (tapped) {
                    drawText(canvas, "Edit recipe", getHeight() / 2f, Color.BLACK, 88);
                    return;
                }
                float firstRow = getHeight() / 2f - 260;
                float secondRow = getHeight() / 2f + 260;
                drawTextAt(canvas, "Chicken Curry", getWidth() * 0.36f, firstRow, Color.BLACK, 52);
                drawTextAt(canvas, "Edit", getWidth() * 0.70f, firstRow, Color.rgb(10, 132, 255), 52);
                drawTextAt(canvas, "Pasta", getWidth() * 0.36f, secondRow, Color.BLACK, 52);
                drawTextAt(canvas, "Edit", getWidth() * 0.70f, secondRow, Color.rgb(10, 132, 255), 52);
                return;
            }
            if (swipeMode) {
                drawText(canvas, swiped ? "Orders" : "Swipe up", getHeight() / 2f, Color.BLACK, 104);
                return;
            }
            if (welcomeInitiallyVisible || tapped) drawText(canvas, "Welcome", getHeight() / 2f - 340, Color.BLACK, 104);
            if (tapped) {
                drawText(canvas, "Tapped", getHeight() / 2f, Color.BLACK, 88);
                return;
            }
            paint.setColor(Color.rgb(10, 132, 255));
            canvas.drawRoundRect(button(), 44, 44, paint);
            drawText(canvas, "Continue", getHeight() / 2f, Color.WHITE, 88);
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            if (spatialMode) {
                if (event.getAction() == MotionEvent.ACTION_UP
                        && spatialButton(getHeight() / 2f - 260).contains(event.getX(), event.getY())) {
                    tapped = true;
                    invalidate();
                }
                return true;
            }
            if (swipeMode) {
                if (event.getAction() == MotionEvent.ACTION_DOWN) touchDownY = event.getY();
                if (event.getAction() == MotionEvent.ACTION_UP && touchDownY - event.getY() >= 200) {
                    swiped = true;
                    invalidate();
                }
                return true;
            }
            if (event.getAction() != MotionEvent.ACTION_UP || !button().contains(event.getX(), event.getY())) return true;
            tapped = true;
            invalidate();
            return true;
        }

        private void drawText(Canvas canvas, String text, float centerY, int color, float size) {
            drawTextAt(canvas, text, getWidth() / 2f, centerY, color, size);
        }

        private void drawTextAt(Canvas canvas, String text, float centerX, float centerY, int color, float size) {
            paint.setColor(color);
            paint.setTextSize(size);
            paint.setFakeBoldText(true);
            paint.setTextAlign(Paint.Align.CENTER);
            Paint.FontMetrics metrics = paint.getFontMetrics();
            canvas.drawText(text, centerX, centerY - (metrics.ascent + metrics.descent) / 2, paint);
        }
    }
}
